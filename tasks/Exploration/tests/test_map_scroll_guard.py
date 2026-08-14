import unittest
from types import SimpleNamespace

import numpy as np

from module.base.timer import Timer
from module.atom.swipe import RuleSwipe
from module.exception import GameTooManyClickError
from tasks.base_task import BaseTask
from tasks.Exploration.base import BaseExploration


class SwipeDevice:
    def __init__(self):
        self.image = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.frame_id = 1
        self.calls = []

    def swipe(self, **kwargs):
        self.calls.append(kwargs)


class SwipeHarness:
    def __init__(self):
        self.device = SwipeDevice()
        self.interval_timer = {}


class EndpointHarness:
    I_SWIPE_END = object()
    _exploration_frame_marker = BaseExploration._exploration_frame_marker
    _wait_for_exploration_new_frame = BaseExploration._wait_for_exploration_new_frame

    def __init__(self, end_results):
        self.device = SimpleNamespace(
            frame_id=1,
            image=np.zeros((720, 1280, 3), dtype=np.uint8),
        )
        self.end_results = iter(end_results)
        self.targets = iter((None, None))

    def appear(self, _rule):
        return next(self.end_results)

    def search_up_fight(self):
        return next(self.targets)

    def screenshot(self):
        self.device.frame_id += 1
        self.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)


class MapScrollGuardTest(unittest.TestCase):
    def _rule(self):
        return RuleSwipe(
            roi_front=(900, 150, 100, 100),
            roi_back=(300, 150, 100, 100),
            mode='vector',
            name='map_scroll',
        )

    def test_swipe_returns_true_only_when_device_executes(self):
        harness = SwipeHarness()
        rule = self._rule()

        self.assertTrue(BaseTask.swipe(harness, rule))
        self.assertEqual(len(harness.device.calls), 1)

        harness.interval_timer[rule.name] = Timer(60).reset()
        self.assertFalse(BaseTask.swipe(harness, rule, interval=60))
        self.assertEqual(len(harness.device.calls), 1)

    def test_swipe_returns_false_when_device_rejects_gesture(self):
        harness = SwipeHarness()
        harness.device.swipe = lambda **_kwargs: False

        self.assertFalse(BaseTask.swipe(harness, self._rule()))

    def test_control_rejection_is_recoverable(self):
        harness = object.__new__(BaseExploration)
        harness.device = SwipeDevice()
        harness.interval_timer = {}
        harness._exploration_last_swipe_failure = None

        def swipe(_rule, interval=None):
            raise GameTooManyClickError('duplicate swipe')

        harness.swipe = swipe

        self.assertFalse(
            BaseExploration._execute_exploration_swipe(
                harness, self._rule(), interval=None
            )
        )
        self.assertEqual(harness._exploration_last_swipe_failure, 'control_rejected')

    def test_endpoint_requires_two_frames(self):
        harness = EndpointHarness([True, True])
        harness._exploration_last_swipe_settled = True

        self.assertTrue(BaseExploration._confirm_exploration_endpoint(harness))

    def test_single_endpoint_frame_is_not_enough(self):
        harness = EndpointHarness([True, False])
        harness._exploration_last_swipe_settled = True

        self.assertFalse(BaseExploration._confirm_exploration_endpoint(harness))

    def test_projected_up_roi_is_clipped_to_frame(self):
        harness = object.__new__(BaseExploration)
        harness.device = SimpleNamespace(
            image=np.zeros((720, 1280, 3), dtype=np.uint8),
        )
        rule = SimpleNamespace(roi_front=[1230, 500, 80, 80])

        self.assertTrue(BaseExploration._clip_exploration_roi_front(harness, rule))
        self.assertEqual(rule.roi_front, [1230, 500, 50, 80])

    def test_unchanged_viewport_is_retried_once(self):
        harness = object.__new__(BaseExploration)
        harness.device = SwipeDevice()
        harness.EXPLORATION_SWIPE_SETTLE_MIN = 0.0
        harness.EXPLORATION_SWIPE_SETTLE_MAX = 0.2
        harness.EXPLORATION_SWIPE_STABLE_FRAMES = 2
        harness.EXPLORATION_SWIPE_RETRY_LIMIT = 1
        harness.interval_timer = {}
        harness.swipe_calls = 0

        def swipe(_rule, interval=None):
            harness.swipe_calls += 1
            return True

        def screenshot():
            harness.device.frame_id += 1
            harness.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)

        harness.swipe = swipe
        harness.screenshot = screenshot

        self.assertTrue(
            BaseExploration._execute_exploration_swipe(
                harness,
                self._rule(),
                interval=3,
            )
        )
        self.assertEqual(harness.swipe_calls, 2)

    def test_viewport_similarity_matches_current_capture_noise(self):
        previous = np.zeros((32, 64), dtype=np.float32)
        current = previous.copy()
        current[::4, ::4] = 6

        self.assertTrue(BaseExploration._exploration_viewport_similar(previous, current))

        changed = previous.copy()
        changed[:, 20:] = 40
        self.assertFalse(BaseExploration._exploration_viewport_similar(previous, changed))

    def test_viewport_signature_ignores_animated_lower_controls(self):
        previous = np.zeros((720, 1280, 3), dtype=np.uint8)
        current = previous.copy()
        current[400:700, 100:1180] = 255

        first = BaseExploration._exploration_viewport_signature(previous)
        second = BaseExploration._exploration_viewport_signature(current)

        self.assertTrue(BaseExploration._exploration_viewport_similar(first, second))

    def test_viewport_signature_detects_background_change(self):
        previous = np.zeros((720, 1280, 3), dtype=np.uint8)
        current = previous.copy()
        current[150:260, 250:1050] = 255

        first = BaseExploration._exploration_viewport_signature(previous)
        second = BaseExploration._exploration_viewport_signature(current)

        self.assertFalse(BaseExploration._exploration_viewport_similar(first, second))


if __name__ == '__main__':
    unittest.main()
