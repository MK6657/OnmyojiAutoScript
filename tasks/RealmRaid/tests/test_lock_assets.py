import unittest

from tasks.RealmRaid.assets import RealmRaidAssets


class RealmRaidLockAssetTest(unittest.TestCase):
    def test_lock_templates_use_current_board_offset(self):
        # RuleImage keeps roi_front mutable so template loading can update its size.
        self.assertEqual(RealmRaidAssets.I_UNLOCK.roi_front[:2], [814, 578])
        self.assertEqual(RealmRaidAssets.I_LOCK.roi_front[:2], [814, 578])
        self.assertEqual(RealmRaidAssets.I_UNLOCK.roi_back, (808, 572, 54, 54))
        self.assertEqual(RealmRaidAssets.I_LOCK.roi_back, (808, 572, 54, 54))


if __name__ == '__main__':
    unittest.main()
