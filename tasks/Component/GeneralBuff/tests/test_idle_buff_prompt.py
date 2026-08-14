import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from module.config.utils import convert_to_underscore
from module.exception import GameStuckError
from tasks.Component.CommonPopup.dispatcher import CommonPopupDispatcher
from tasks.Component.CommonPopup.models import PopupFrameContext
from tasks.Component.GeneralBuff.idle_prompt import (
    LongIdleBuffPromptChoice,
    LongIdleBuffPromptGuard,
)
from tasks.GlobalGame.config_emergency import CommonPopupMode, Emergency


def modal_frame() -> np.ndarray:
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[250:470, 430:860] = 230
    return image


def clean_frame() -> np.ndarray:
    return np.full((720, 1280, 3), 32, dtype=np.uint8)


class FakeDevice:
    def __init__(self, frames):
        self.frames = list(frames)
        self.image = self.frames.pop(0)
        self.frame_id = 1
        self.serial = '127.0.0.1:16384'
        self.clicks = []

    def screenshot(self):
        if not self.frames:
            raise AssertionError('unexpected screenshot')
        self.image = self.frames.pop(0)
        self.frame_id += 1
        return self.image

    def click(self, x, y, control_name=None):
        self.clicks.append((x, y, control_name))


class PromptTask:
    def __init__(
        self,
        frames,
        mode=CommonPopupMode.ENFORCE,
        running_task='Exploration',
        task_config=None,
    ):
        self.device = FakeDevice(frames)
        device_config = SimpleNamespace(
            serial='127.0.0.1:16384',
            screenshot_method='nemu_ipc',
        )
        model = SimpleNamespace(running_task=running_task)
        if task_config is None and running_task == 'Exploration':
            task_config = SimpleNamespace(
                exploration_config=SimpleNamespace(
                    buff_gold_50_click=True,
                    buff_gold_100_click=False,
                    buff_exp_50_click=False,
                    buff_exp_100_click=False,
                )
            )
        if task_config is not None:
            task_key = convert_to_underscore(running_task)
            setattr(model, task_key, task_config)
        self.config = SimpleNamespace(
            config_name='test',
            script=SimpleNamespace(device=device_config),
            model=model,
            global_game=SimpleNamespace(
                emergency=SimpleNamespace(long_idle_buff_prompt_mode=mode)
            ),
        )


class LongIdleBuffPromptGuardTest(unittest.TestCase):
    def test_safe_random_points_stay_inside_half_open_confirm_area(self):
        guard = LongIdleBuffPromptGuard(rng=random.Random(20260809))
        recent = []

        points = [guard.choose_confirm_point(recent) for _ in range(200)]

        self.assertTrue(all(705 <= x < 778 for x, _ in points))
        self.assertTrue(all(411 <= y < 434 for _, y in points))

    def test_recent_point_is_not_reused_when_other_points_exist(self):
        guard = LongIdleBuffPromptGuard(rng=random.Random(7))
        first = guard.choose_confirm_point([])

        second = guard.choose_confirm_point([first])

        self.assertNotEqual(second, first)

    def test_safe_random_cancel_points_stay_inside_calibrated_area(self):
        guard = LongIdleBuffPromptGuard(rng=random.Random(20260810))
        recent = []

        points = [guard.choose_cancel_point(recent) for _ in range(200)]

        self.assertTrue(all(502 <= x < 568 for x, _ in points))
        self.assertTrue(all(411 <= y < 434 for _, y in points))

    def test_ryou_without_buff_controls_chooses_cancel(self):
        guard = LongIdleBuffPromptGuard()
        task = PromptTask(
            [modal_frame()],
            running_task='RyouToppa',
            task_config=SimpleNamespace(),
        )

        intent = guard.resolve_buff_intent(task)

        self.assertEqual(intent.choice, LongIdleBuffPromptChoice.CANCEL)
        self.assertEqual(intent.task_name, 'ryou_toppa')
        self.assertEqual(intent.enabled_fields, ())

    def test_exploration_with_any_requested_buff_chooses_confirm(self):
        guard = LongIdleBuffPromptGuard()
        task = PromptTask([modal_frame()])

        intent = guard.resolve_buff_intent(task)

        self.assertEqual(intent.choice, LongIdleBuffPromptChoice.CONFIRM)
        self.assertEqual(
            intent.enabled_fields,
            ('exploration_config.buff_gold_50_click',),
        )

    def test_exploration_without_requested_buff_chooses_cancel(self):
        guard = LongIdleBuffPromptGuard()
        task = PromptTask(
            [modal_frame()],
            running_task='Exploration',
            task_config=SimpleNamespace(
                exploration_config=SimpleNamespace(
                    buff_gold_50_click=False,
                    buff_gold_100_click=False,
                    buff_exp_50_click=False,
                    buff_exp_100_click=False,
                )
            ),
        )

        intent = guard.resolve_buff_intent(task)

        self.assertEqual(intent.choice, LongIdleBuffPromptChoice.CANCEL)

    def test_disabled_task_level_buff_gate_chooses_cancel(self):
        guard = LongIdleBuffPromptGuard()
        task = PromptTask(
            [modal_frame()],
            running_task='Sougenbi',
            task_config=SimpleNamespace(
                sougenbi_config=SimpleNamespace(
                    buff_enable=False,
                    buff_gold_50_click=True,
                    buff_gold_100_click=False,
                    buff_exp_50_click=False,
                    buff_exp_100_click=False,
                )
            ),
        )

        intent = guard.resolve_buff_intent(task)

        self.assertEqual(intent.choice, LongIdleBuffPromptChoice.CANCEL)
        self.assertEqual(intent.reason, 'task_buff_gate_disabled')

    def test_enabled_task_level_buff_gate_and_requested_buff_choose_confirm(self):
        guard = LongIdleBuffPromptGuard()
        task = PromptTask(
            [modal_frame()],
            running_task='Sougenbi',
            task_config=SimpleNamespace(
                sougenbi_config=SimpleNamespace(
                    buff_enable=True,
                    buff_gold_50_click=False,
                    buff_gold_100_click=False,
                    buff_exp_50_click=True,
                    buff_exp_100_click=False,
                )
            ),
        )

        intent = guard.resolve_buff_intent(task)

        self.assertEqual(intent.choice, LongIdleBuffPromptChoice.CONFIRM)
        self.assertEqual(
            intent.enabled_fields,
            ('sougenbi_config.buff_exp_50_click',),
        )

    def test_every_registered_task_uses_its_real_config_path(self):
        cases = (
            (
                'ExperienceYoukai',
                SimpleNamespace(experience_youkai=SimpleNamespace(
                    buff_exp_50_click=True,
                    buff_exp_100_click=False,
                )),
            ),
            (
                'GoldYoukai',
                SimpleNamespace(gold_youkai=SimpleNamespace(
                    buff_gold_50_click=True,
                    buff_gold_100_click=False,
                )),
            ),
            (
                'Nian',
                SimpleNamespace(nian_config=SimpleNamespace(
                    buff_gold_50_click=True,
                    buff_gold_100_click=False,
                )),
            ),
            (
                'Tako',
                SimpleNamespace(tako_config=SimpleNamespace(
                    enable=True,
                    buff_gold_50_click=True,
                    buff_gold_100_click=False,
                    buff_exp_50_click=False,
                    buff_exp_100_click=False,
                )),
            ),
            (
                'Secret',
                SimpleNamespace(secret_config=SimpleNamespace(
                    secret_gold_50=True,
                    secret_gold_100=False,
                )),
            ),
            (
                'HeroTest',
                SimpleNamespace(herotest=SimpleNamespace(
                    exp_50_buff_enable_help=True,
                    exp_100_buff_enable_help=False,
                )),
            ),
            (
                'EvoZone',
                SimpleNamespace(evo_zone_config=SimpleNamespace(
                    soul_buff_enable=True,
                )),
            ),
            (
                'Orochi',
                SimpleNamespace(orochi_config=SimpleNamespace(
                    soul_buff_enable=True,
                )),
            ),
        )
        guard = LongIdleBuffPromptGuard()

        for running_task, task_config in cases:
            with self.subTest(running_task=running_task):
                task = PromptTask(
                    [modal_frame()],
                    running_task=running_task,
                    task_config=task_config,
                )
                intent = guard.resolve_buff_intent(task)
                self.assertEqual(intent.choice, LongIdleBuffPromptChoice.CONFIRM)
                self.assertTrue(intent.enabled_fields)

    def test_prompt_requires_all_stable_keywords(self):
        complete = ''.join(LongIdleBuffPromptGuard.REQUIRED_KEYWORDS)

        self.assertTrue(LongIdleBuffPromptGuard.has_prompt_keywords(complete))
        self.assertFalse(LongIdleBuffPromptGuard.has_prompt_keywords('confirm exploration exit'))
        self.assertFalse(LongIdleBuffPromptGuard.has_prompt_keywords(complete[:-1]))

    def test_prefilter_rejects_plain_frame_and_accepts_modal_layout(self):
        plain = np.zeros((720, 1280, 3), dtype=np.uint8)

        self.assertFalse(LongIdleBuffPromptGuard.looks_like_prompt(plain))
        self.assertTrue(LongIdleBuffPromptGuard.looks_like_prompt(modal_frame()))

    def test_default_mode_preserves_enforced_confirmation(self):
        self.assertEqual(
            Emergency().long_idle_buff_prompt_mode,
            CommonPopupMode.ENFORCE,
        )

    def test_disabled_mode_skips_detection(self):
        guard = LongIdleBuffPromptGuard()
        task = PromptTask([modal_frame()], mode=CommonPopupMode.DISABLED)
        context = PopupFrameContext.from_task(task)

        with patch.object(guard.PROMPT_OCR, 'detect_text') as ocr:
            detection = guard.detect(context)

        self.assertIsNone(detection)
        ocr.assert_not_called()

    def test_detect_block_mode_never_clicks(self):
        guard = LongIdleBuffPromptGuard()
        task = PromptTask([modal_frame()], mode=CommonPopupMode.DETECT_BLOCK)
        dispatcher = CommonPopupDispatcher(
            (guard,),
            poll_interval=0,
            evidence_enabled=False,
        )
        complete = ''.join(LongIdleBuffPromptGuard.REQUIRED_KEYWORDS)

        with patch.object(guard.PROMPT_OCR, 'detect_text', return_value=complete):
            with self.assertRaisesRegex(GameStuckError, 'detect_block_mode'):
                dispatcher.stabilize(task)

        self.assertEqual(task.device.clicks, [])

    def test_enforce_click_uses_safe_area_and_two_absent_frames(self):
        guard = LongIdleBuffPromptGuard(rng=random.Random(1))
        task = PromptTask([
            modal_frame(),
            clean_frame(),
            clean_frame(),
        ])
        dispatcher = CommonPopupDispatcher(
            (guard,),
            poll_interval=0,
            evidence_enabled=False,
        )
        complete = ''.join(LongIdleBuffPromptGuard.REQUIRED_KEYWORDS)

        with patch.object(guard.PROMPT_OCR, 'detect_text', return_value=complete) as ocr:
            report = dispatcher.stabilize(task)

        self.assertEqual(report.actions, 1)
        self.assertEqual(len(task.device.clicks), 1)
        x, y, _ = task.device.clicks[0]
        self.assertTrue(705 <= x < 778)
        self.assertTrue(411 <= y < 434)
        self.assertEqual(ocr.call_count, 1)

    def test_enforce_without_requested_buff_clicks_cancel_area(self):
        guard = LongIdleBuffPromptGuard(rng=random.Random(3))
        task = PromptTask(
            [modal_frame(), clean_frame(), clean_frame()],
            running_task='RyouToppa',
            task_config=SimpleNamespace(),
        )
        dispatcher = CommonPopupDispatcher(
            (guard,),
            poll_interval=0,
            evidence_enabled=False,
        )
        complete = ''.join(LongIdleBuffPromptGuard.REQUIRED_KEYWORDS)

        with patch.object(guard.PROMPT_OCR, 'detect_text', return_value=complete):
            report = dispatcher.stabilize(task)

        self.assertEqual(report.actions, 1)
        x, y, control_name = task.device.clicks[0]
        self.assertTrue(502 <= x < 568)
        self.assertTrue(411 <= y < 434)
        self.assertEqual(control_name, 'LONG_IDLE_BUFF_PROMPT_CANCEL')
        detected = next(
            event for event in report.events
            if event.get('event') == 'popup_detected'
        )
        self.assertEqual(detected['evidence']['choice'], 'cancel')

    def test_persistent_prompt_clicks_once_then_fails_closed(self):
        guard = LongIdleBuffPromptGuard(rng=random.Random(2))
        task = PromptTask([modal_frame(), modal_frame(), modal_frame()])
        dispatcher = CommonPopupDispatcher(
            (guard,),
            poll_interval=0,
            evidence_enabled=False,
        )
        complete = ''.join(LongIdleBuffPromptGuard.REQUIRED_KEYWORDS)

        with patch.object(guard.PROMPT_OCR, 'detect_text', return_value=complete) as ocr:
            with self.assertRaises(GameStuckError):
                dispatcher.stabilize(task)

        self.assertEqual(len(task.device.clicks), 1)
        self.assertLessEqual(ocr.call_count, 2)


if __name__ == '__main__':
    unittest.main()
