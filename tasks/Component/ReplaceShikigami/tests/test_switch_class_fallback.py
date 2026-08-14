import unittest

from tasks.Component.ReplaceShikigami.assets import ReplaceShikigamiAssets
from tasks.Component.ReplaceShikigami.replace_shikigami import ReplaceShikigami
from tasks.Utils.config_enum import ShikigamiClass


class SwitchClassFallbackHarness(ReplaceShikigamiAssets):
    def __init__(self):
        self.clicks = []

    def screenshot(self):
        return None

    def appear(self, _rule, *args, **kwargs):
        return False

    def wait_animate_stable(self, rule, interval=0.8):
        return True

    def click(self, rule, interval=None):
        self.clicks.append((rule.name, interval))
        return False


class SwitchClassFallbackTest(unittest.TestCase):
    def test_material_skin_fallback_does_not_repeatedly_click_all(self):
        harness = SwitchClassFallbackHarness()

        result = ReplaceShikigami.switch_shikigami_class(
            harness,
            ShikigamiClass.MATERIAL,
            fallback_click=harness.C_SHIKIGAMI_CLASS_MATERIAL,
        )

        self.assertTrue(result)
        self.assertEqual(
            [name for name, _interval in harness.clicks],
            ['shikigami_category_all', 'shikigami_class_material'],
        )


if __name__ == '__main__':
    unittest.main()
