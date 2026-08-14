import ast
import json
import tempfile
import time
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from module.exception import GameStuckError
from tasks.Component.CommonPopup.dispatcher import CommonPopupDispatcher
from tasks.Component.CommonPopup.friend_invitation import FriendInvitationPopupHandler
from tasks.Component.CommonPopup.models import (
    PopupActionKind,
    PopupActionResult,
    PopupDetection,
    PopupDispatchStatus,
    PopupFrameContext,
)
from tasks.base_task import BaseTask
from tasks.GlobalGame.config_emergency import FriendInvitation


def frame(code: int) -> np.ndarray:
    image = np.full((720, 1280, 3), 32, dtype=np.uint8)
    image[0, 0, 0] = code
    return image


class FakeDevice:
    def __init__(self, frames, *, advance_frame=True):
        self.frames = deque(frames)
        self.image = None
        self.frame_id = 0
        self.serial = '127.0.0.1:16384'
        self.screenshot_calls = 0
        self.clicks = []
        self.detect_record = ['battle-state']
        self.advance_frame = advance_frame
        self.raise_on_call = None
        self.serial_after_first = None
        self.on_screenshot = None

    def screenshot(self):
        self.screenshot_calls += 1
        if self.on_screenshot is not None:
            self.on_screenshot()
        if self.raise_on_call == self.screenshot_calls:
            raise RuntimeError('capture failed')
        if not self.frames:
            raise AssertionError('unexpected screenshot')
        self.image = self.frames.popleft()
        if self.serial_after_first is not None and self.screenshot_calls > 1:
            self.serial = self.serial_after_first
        if self.advance_frame or self.frame_id == 0:
            self.frame_id += 1
        return self.image

    def click(self, x, y, control_name=None):
        self.clicks.append((x, y, control_name))
        self.detect_record = []


class FakeTask:
    def __init__(self, frames, *, advance_frame=True):
        self.device = FakeDevice(frames, advance_frame=advance_frame)
        device_config = SimpleNamespace(
            serial='127.0.0.1:16384',
            screenshot_method='nemu_ipc',
        )
        self.config = SimpleNamespace(
            config_name='test',
            script=SimpleNamespace(device=device_config),
            model=SimpleNamespace(running_task='Exploration'),
        )
        self.resolved = []
        self.scheduled = []

    def appear(self, target, **kwargs):
        return target.match(self.device.image)

    def set_next_run(self, **kwargs):
        self.scheduled.append(kwargs)


class CodeHandler:
    verify_absent_frames = 2
    max_actions = 2

    def __init__(self, popup_id, code, priority):
        self.popup_id = popup_id
        self.code = code
        self.priority = priority

    def detect(self, context):
        if int(context.image[0, 0, 0]) != self.code:
            return None
        return PopupDetection(
            popup_id=self.popup_id,
            priority=self.priority,
            frame_id=context.frame_id,
            instance_key=self.popup_id,
            pixel_sha256=context.pixel_sha256(),
            evidence={'code': self.code},
        )

    def act(self, context, detection, attempt):
        point = (100 + self.code, 200 + self.code)
        context.click(*point, control_name=self.popup_id)
        return PopupActionResult(
            kind=PopupActionKind.CLICKED,
            control_name=self.popup_id,
            click_point=point,
            attempt=attempt,
            reason='test_click',
        )

    def on_resolved(self, task, detection, action):
        task.resolved.append(self.popup_id)

    def on_abort(self, task, detection, reason):
        return None


class DeadlineHandler(CodeHandler):
    required_deadline_capabilities = ('capture',)

    def __init__(self, popup_id, code, priority):
        super().__init__(popup_id, code, priority)
        self.detect_deadline = None
        self.act_deadline = None

    def detect(self, context):
        self.detect_deadline = context.deadline_at
        return super().detect(context)

    def act(self, context, detection, attempt):
        self.act_deadline = context.deadline_at
        return super().act(context, detection, attempt)


class BrokenActionHandler(CodeHandler):
    def act(self, context, detection, attempt):
        raise RuntimeError('click failed')


class BrokenResolvedHandler(CodeHandler):
    def on_resolved(self, task, detection, action):
        raise RuntimeError('schedule failed')


class BrokenAbortHandler(CodeHandler):
    def on_abort(self, task, detection, reason):
        raise RuntimeError('abort logging failed')


class MultiCodeHandler(CodeHandler):
    def __init__(self, popup_id, codes, priority):
        super().__init__(popup_id, next(iter(codes)), priority)
        self.codes = set(codes)

    def detect(self, context):
        code = int(context.image[0, 0, 0])
        if code not in self.codes:
            return None
        return PopupDetection(
            popup_id=self.popup_id,
            priority=self.priority,
            frame_id=context.frame_id,
            instance_key=self.popup_id,
            pixel_sha256=context.pixel_sha256(),
            evidence={'code': code},
        )


class FakeTarget:
    def __init__(self, name, bit, point):
        self.name = name
        self.bit = bit
        self.point = point

    def match(self, image, threshold=None):
        return bool(int(image[0, 0, 0]) & self.bit)

    def coord(self):
        return self.point


class InvitationTask(FakeTask):
    def __init__(self, frames):
        super().__init__(frames)
        self.config.global_game = SimpleNamespace(
            emergency=SimpleNamespace(friend_invitation=FriendInvitation.ONLY_JADE)
        )
        self.I_G_ACCEPT = FakeTarget('accept', 1, (10, 10))
        self.I_G_REJECT = FakeTarget('reject', 1, (20, 20))
        self.I_G_IGNORE = FakeTarget('ignore', 1, (30, 30))
        self.I_G_JADE = FakeTarget('jade', 2, (0, 0))
        self.I_G_CAT_FOOD = FakeTarget('cat', 4, (0, 0))
        self.I_G_DOG_FOOD = FakeTarget('dog', 8, (0, 0))


class CommonPopupDispatcherTest(unittest.TestCase):
    def dispatcher(self, handlers, **kwargs):
        return CommonPopupDispatcher(
            handlers,
            poll_interval=0,
            evidence_enabled=False,
            **kwargs,
        )

    def test_clean_frame_has_one_capture_and_no_extra_work(self):
        task = FakeTask([frame(0)])
        report = self.dispatcher((CodeHandler('idle', 1, 900),)).capture_and_stabilize(task)

        self.assertEqual(report.status, PopupDispatchStatus.STABLE)
        self.assertEqual(report.actions, 0)
        self.assertEqual(task.device.screenshot_calls, 1)

    def test_base_task_screenshot_uses_dispatcher_as_the_only_capture_owner(self):
        task = FakeTask([frame(0)])
        dispatcher = self.dispatcher((CodeHandler('idle', 1, 900),))
        task._get_common_popup_dispatcher = lambda: dispatcher
        task.screenshot = BaseTask.screenshot.__get__(task, FakeTask)

        image = task.screenshot()

        self.assertIs(image, task.device.image)
        self.assertEqual(task.device.screenshot_calls, 1)
        self.assertEqual(task._last_popup_dispatch_report.status, PopupDispatchStatus.STABLE)

    def test_idle_then_invitation_is_stabilized_before_return(self):
        task = FakeTask([frame(1), frame(2), frame(0), frame(0)])
        handlers = (
            CodeHandler('idle', 1, 900),
            CodeHandler('invitation', 2, 800),
        )

        report = self.dispatcher(handlers).capture_and_stabilize(task)

        self.assertEqual(report.status, PopupDispatchStatus.HANDLED)
        self.assertEqual([item[2] for item in task.device.clicks], ['idle', 'invitation'])
        self.assertEqual(task.resolved, ['idle', 'invitation'])
        self.assertEqual(task.device.screenshot_calls, 4)

    def test_invitation_then_idle_restarts_from_highest_priority(self):
        task = FakeTask([frame(2), frame(1), frame(0), frame(0)])
        handlers = (
            CodeHandler('idle', 1, 900),
            CodeHandler('invitation', 2, 800),
        )

        self.dispatcher(handlers).capture_and_stabilize(task)

        self.assertEqual([item[2] for item in task.device.clicks], ['invitation', 'idle'])
        self.assertEqual(task.resolved, ['invitation', 'idle'])

    def test_two_detections_on_one_frame_choose_the_higher_priority(self):
        task = FakeTask([frame(3), frame(2), frame(0), frame(0)])
        handlers = (
            MultiCodeHandler('central', {3}, 900),
            MultiCodeHandler('side', {2, 3}, 800),
        )

        self.dispatcher(handlers).capture_and_stabilize(task)

        self.assertEqual([item[2] for item in task.device.clicks], ['central', 'side'])

    def test_lost_first_click_retries_then_requires_two_absent_frames(self):
        task = FakeTask([frame(1), frame(1), frame(0), frame(0)])

        report = self.dispatcher((CodeHandler('idle', 1, 900),)).capture_and_stabilize(task)

        self.assertEqual(report.actions, 2)
        self.assertEqual(len(task.device.clicks), 2)
        self.assertEqual(task.resolved, ['idle'])

    def test_handler_post_action_delay_overrides_default_poll_interval(self):
        task = FakeTask([frame(1), frame(0), frame(0)])
        handler = CodeHandler('idle', 1, 900)
        handler.post_action_delay = 0.8
        sleeps = []
        dispatcher = CommonPopupDispatcher(
            (handler,),
            poll_interval=0.2,
            sleep_fn=sleeps.append,
            evidence_enabled=False,
        )

        dispatcher.capture_and_stabilize(task)

        self.assertEqual(sleeps, [0.8, 0.2])

    def test_persistent_popup_fails_closed_after_two_actions(self):
        task = FakeTask([frame(1), frame(1), frame(1)])

        with self.assertRaises(GameStuckError):
            self.dispatcher((CodeHandler('idle', 1, 900),)).capture_and_stabilize(task)

        self.assertEqual(len(task.device.clicks), 2)
        self.assertEqual(task.device.screenshot_calls, 3)

    def test_post_action_frame_id_must_advance(self):
        task = FakeTask([frame(1), frame(0)], advance_frame=False)

        with self.assertRaisesRegex(GameStuckError, 'did not advance frame_id'):
            self.dispatcher((CodeHandler('idle', 1, 900),)).capture_and_stabilize(task)

    def test_post_action_capture_error_fails_closed(self):
        task = FakeTask([frame(1), frame(0)])
        task.device.raise_on_call = 2

        with self.assertRaisesRegex(GameStuckError, 'verification_capture_error|post_action_capture_error'):
            self.dispatcher((CodeHandler('idle', 1, 900),)).capture_and_stabilize(task)

        self.assertEqual(len(task.device.clicks), 1)

    def test_device_identity_change_fails_closed(self):
        task = FakeTask([frame(1), frame(0)])
        task.device.serial_after_first = '127.0.0.1:16416'

        with self.assertRaisesRegex(GameStuckError, 'device identity changed'):
            self.dispatcher((CodeHandler('idle', 1, 900),)).capture_and_stabilize(task)

    def test_wrong_initial_frame_size_is_rejected_before_detection(self):
        wrong = np.zeros((413, 710, 3), dtype=np.uint8)
        task = FakeTask([wrong])

        with self.assertRaisesRegex(GameStuckError, 'initial_frame_size_invalid'):
            self.dispatcher((CodeHandler('idle', 1, 900),)).capture_and_stabilize(task)

        self.assertEqual(task.device.clicks, [])

    def test_black_initial_frame_is_rejected_before_business_logic(self):
        task = FakeTask([np.zeros((720, 1280, 3), dtype=np.uint8)])

        with self.assertRaisesRegex(GameStuckError, 'initial_frame_black'):
            self.dispatcher((CodeHandler('idle', 1, 900),)).capture_and_stabilize(task)

        self.assertEqual(task.device.clicks, [])

    def test_black_post_action_frame_cannot_confirm_resolution(self):
        black = np.zeros((720, 1280, 3), dtype=np.uint8)
        task = FakeTask([frame(1), black])

        with self.assertRaisesRegex(GameStuckError, 'frame_black'):
            self.dispatcher((CodeHandler('idle', 1, 900),)).capture_and_stabilize(task)

        self.assertEqual(len(task.device.clicks), 1)

    def test_elapsed_budget_is_checked_before_any_handler_action(self):
        task = FakeTask([frame(1)])
        task.device.screenshot()
        timestamps = iter((0.0, 7.0, 7.0, 7.0))
        dispatcher = self.dispatcher(
            (CodeHandler('idle', 1, 900),),
            time_fn=lambda: next(timestamps),
        )

        with self.assertRaisesRegex(GameStuckError, 'budget_exhausted'):
            dispatcher.stabilize(task)

        self.assertEqual(task.device.clicks, [])

    def test_initial_capture_time_is_inside_the_global_budget(self):
        task = FakeTask([frame(1)])
        clock = [0.0]
        task.device.on_screenshot = lambda: clock.__setitem__(0, 7.0)
        dispatcher = self.dispatcher(
            (CodeHandler('idle', 1, 900),),
            max_elapsed=6.0,
            time_fn=lambda: clock[0],
        )

        with self.assertRaisesRegex(GameStuckError, 'budget_exhausted'):
            dispatcher.capture_and_stabilize(task)

        self.assertEqual(task.device.clicks, [])

    def test_deadline_is_passed_to_detection_and_action(self):
        task = FakeTask([frame(1), frame(0), frame(0)])
        handler = DeadlineHandler('idle', 1, 900)

        self.dispatcher((handler,), max_elapsed=6.0).capture_and_stabilize(task)

        self.assertIsNotNone(handler.detect_deadline)
        self.assertEqual(handler.detect_deadline, handler.act_deadline)

    def test_backend_without_deadline_support_cannot_enforce(self):
        task = FakeTask([frame(1)])
        handler = DeadlineHandler('idle', 1, 900)

        with self.assertRaisesRegex(GameStuckError, 'deadline_capability_missing:capture'):
            self.dispatcher((handler,)).capture_and_stabilize(
                task,
                capture_deadline_capable=False,
            )

        self.assertEqual(task.device.clicks, [])

    def test_popup_ocr_is_cut_off_by_the_same_deadline(self):
        class SlowRule:
            @staticmethod
            def detect_text(image):
                time.sleep(0.2)
                return 'late'

        task = FakeTask([frame(0)])
        task._common_popup_ocr_text = BaseTask._common_popup_ocr_text.__get__(
            task,
            FakeTask,
        )
        context = PopupFrameContext.from_task(
            task,
            deadline_at=time.monotonic() + 0.03,
        )

        started_at = time.monotonic()
        with self.assertRaisesRegex(GameStuckError, 'OCR exceeded'):
            context.ocr_text(SlowRule())

        self.assertLess(time.monotonic() - started_at, 0.15)

    def test_action_exception_is_structured_failure(self):
        task = FakeTask([frame(1)])

        with self.assertRaisesRegex(GameStuckError, 'action_error'):
            self.dispatcher((BrokenActionHandler('idle', 1, 900),)).capture_and_stabilize(task)

    def test_resolution_callback_error_fails_closed(self):
        task = FakeTask([frame(1), frame(0), frame(0)])

        with self.assertRaisesRegex(GameStuckError, 'resolution_callback_error'):
            self.dispatcher(
                (BrokenResolvedHandler('idle', 1, 900),)
            ).capture_and_stabilize(task)

        self.assertEqual(len(task.device.clicks), 1)

    def test_abort_callback_error_does_not_mask_primary_failure(self):
        task = FakeTask([frame(1), frame(1), frame(1)])

        with self.assertRaisesRegex(GameStuckError, 'action_budget_exhausted'):
            self.dispatcher(
                (BrokenAbortHandler('idle', 1, 900),)
            ).capture_and_stabilize(task)

    def test_evidence_contains_before_and_stable_frames_with_hashes(self):
        task = FakeTask([frame(1), frame(0), frame(0)])
        with tempfile.TemporaryDirectory() as directory:
            dispatcher = CommonPopupDispatcher(
                (CodeHandler('idle', 1, 900),),
                poll_interval=0,
                evidence_root=Path(directory),
                evidence_enabled=True,
            )
            report = dispatcher.capture_and_stabilize(task)
            manifests = list(Path(directory).rglob('manifest.json'))

            self.assertEqual(len(manifests), 1)
            data = json.loads(manifests[0].read_text(encoding='utf-8'))
            self.assertEqual(data['status'], 'handled')
            self.assertEqual(len(data['frames']), 3)
            self.assertTrue(all(item['file_sha256'] for item in data['frames']))
            self.assertTrue(all(item['pixel_sha256'] for item in data['frames']))
            self.assertEqual(report.evidence_event_id, data['event_id'])

    def test_consecutive_invitation_types_recompute_the_policy(self):
        # 3 = invitation+jade, 5 = invitation+cat-food.
        task = InvitationTask([frame(3), frame(5), frame(0), frame(0)])
        original_detect_record = task.device.detect_record

        report = self.dispatcher((FriendInvitationPopupHandler(),)).capture_and_stabilize(task)

        self.assertEqual(report.actions, 2)
        self.assertEqual([item[2] for item in task.device.clicks], ['accept', 'ignore'])
        self.assertIs(task.device.detect_record, original_detect_record)
        self.assertEqual(len(task.scheduled), 1)
        self.assertEqual(task.scheduled[0]['task'], 'WantedQuests')

    def test_same_reward_new_invitation_has_a_distinct_instance_key(self):
        task = InvitationTask([frame(3)])
        handler = FriendInvitationPopupHandler()
        first = frame(3)
        second = frame(3)
        first[140:220, 500:760] = 70
        second[140:220, 500:760] = 180

        task.device.image = first
        task.device.frame_id = 1
        first_detection = handler.detect(
            PopupFrameContext.from_task(task, deadline_at=10.0, time_fn=lambda: 0.0)
        )
        task.device.image = second
        task.device.frame_id = 2
        second_detection = handler.detect(
            PopupFrameContext.from_task(task, deadline_at=10.0, time_fn=lambda: 0.0)
        )

        self.assertNotEqual(first_detection.instance_key, second_detection.instance_key)

    def test_string_invitation_policy_is_normalized(self):
        task = InvitationTask([frame(1), frame(0), frame(0)])
        task.config.global_game.emergency.friend_invitation = 'reject'

        report = self.dispatcher(
            (FriendInvitationPopupHandler(),)
        ).capture_and_stabilize(task)

        self.assertEqual(report.status, PopupDispatchStatus.HANDLED)
        self.assertEqual([item[2] for item in task.device.clicks], ['reject'])

    def test_business_code_cannot_call_raw_device_screenshot(self):
        root = Path(__file__).resolve().parents[4]
        allowed = {
            Path('tasks/Component/CommonPopup/dispatcher.py').as_posix(),
        }
        offenders = set()
        for path in (root / 'tasks').rglob('*.py'):
            relative = path.relative_to(root).as_posix()
            if '/tests/' in f'/{relative}/':
                continue
            tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr != 'screenshot':
                    continue
                value = node.func.value
                if isinstance(value, ast.Attribute) and value.attr == 'device':
                    offenders.add(relative)
        self.assertEqual(offenders, allowed)


if __name__ == '__main__':
    unittest.main()
