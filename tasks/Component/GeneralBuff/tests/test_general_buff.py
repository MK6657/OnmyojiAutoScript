import unittest

from tasks.Component.GeneralBuff.general_buff import GeneralBuff


class FakeBuff:
    name = "TARGET_BUFF"
    keyword = "目标加成"

    def __init__(self, text, area=(100, 200, 50, 20)):
        self.text = text
        self.area = area
        self.ocr_calls = 0

    def detect_text(self, _image):
        return self.text

    def ocr(self, _image):
        self.ocr_calls += 1
        return self.area


class GeneralBuffHarness:
    class Device:
        image = object()

    device = Device()

    def reject_invite(self):
        return None

    def screenshot(self):
        return None


class FakeSwitchRule:
    def __init__(self, state):
        self.state = state


class SwitchStateHarness:
    def __init__(self, state):
        self.state = state
        self.clicks = []

    def set_switch_area(self, _area):
        return FakeSwitchRule('open'), FakeSwitchRule('closed')

    def screenshot(self):
        return None

    def appear(self, rule):
        return rule.state == self.state

    def ui_click(self, click, stop, **_kwargs):
        self.clicks.append((click.state, stop.state))
        self.state = stop.state
        return True


class GeneralBuffLookupTest(unittest.TestCase):
    def test_missing_keyword_does_not_use_fuzzy_ocr_coordinate(self):
        buff = FakeBuff("觉醒副本掉落额外的觉醒材料")

        area = GeneralBuff.get_area(GeneralBuffHarness(), buff)

        self.assertIsNone(area)
        self.assertEqual(buff.ocr_calls, 0)

    def test_exact_keyword_returns_switch_area(self):
        buff = FakeBuff("目标加成")

        area = GeneralBuff.get_area(GeneralBuffHarness(), buff)

        self.assertEqual(area, (160, 190, 80, 40))
        self.assertEqual(buff.ocr_calls, 1)

    def test_switch_area_does_not_mutate_class_asset_roi(self):
        harness = GeneralBuffHarness()
        harness.I_OPEN_YELLOW = GeneralBuff.I_OPEN_YELLOW
        harness.I_CLOSE_RED = GeneralBuff.I_CLOSE_RED
        open_before = tuple(GeneralBuff.I_OPEN_YELLOW.roi_back)
        close_before = tuple(GeneralBuff.I_CLOSE_RED.roi_back)

        open_rule, close_rule = GeneralBuff.set_switch_area(harness, (10, 20, 30, 40))

        self.assertEqual(open_rule.roi_back, (10, 20, 30, 40))
        self.assertEqual(close_rule.roi_back, (10, 20, 30, 40))
        self.assertEqual(tuple(GeneralBuff.I_OPEN_YELLOW.roi_back), open_before)
        self.assertEqual(tuple(GeneralBuff.I_CLOSE_RED.roi_back), close_before)

    def test_unknown_switch_state_returns_without_repeated_clicks(self):
        harness = SwitchStateHarness('missing')

        result = GeneralBuff._set_switch_state(harness, 'gold_100', (1, 2, 3, 4), True)

        self.assertFalse(result)
        self.assertEqual(harness.clicks, [])

    def test_closed_switch_transitions_once_and_confirms(self):
        harness = SwitchStateHarness('closed')

        result = GeneralBuff._set_switch_state(harness, 'gold_100', (1, 2, 3, 4), True)

        self.assertTrue(result)
        self.assertEqual(harness.clicks, [('closed', 'open')])

if __name__ == "__main__":
    unittest.main()
