import unittest

from tasks.Component.GeneralBattle.general_battle import GeneralBattle


class BattleStateGuardHarness:
    I_BATTLE_INFO = object()
    I_FRIENDS = object()
    I_WIN = object()
    I_FALSE = object()
    I_REWARD = object()
    O_BATTLE_RESULT_CONTINUE = object()

    is_in_real_battle = GeneralBattle.is_in_real_battle
    _battle_result_continue_visible = GeneralBattle._battle_result_continue_visible

    def __init__(self, prepare=False, friends=True, result=None):
        self.prepare = prepare
        self.friends = friends
        self.result = result

    def _prepare_button_visible(self):
        return self.prepare

    def ocr_appear(self, _target, **_kwargs):
        return False

    def appear(self, target, **_kwargs):
        if target is self.I_FRIENDS:
            return self.friends
        if target in (self.I_WIN, self.I_FALSE, self.I_REWARD):
            return target is self.result
        return False


class BattleStateGuardTest(unittest.TestCase):
    def test_prepare_page_with_friends_icon_is_not_real_battle(self):
        self.assertFalse(BattleStateGuardHarness(prepare=True).is_in_real_battle(False))

    def test_real_battle_uses_friends_icon_when_battle_info_template_is_stale(self):
        self.assertTrue(BattleStateGuardHarness(prepare=False).is_in_real_battle(False))

    def test_result_page_is_not_real_battle(self):
        harness = BattleStateGuardHarness(result=BattleStateGuardHarness.I_WIN)
        self.assertFalse(harness.is_in_real_battle(False))


if __name__ == '__main__':
    unittest.main()
