import os
import tempfile
import unittest
from pathlib import Path

from module.server.config_manager import ConfigManager


class ConfigManagerSafetyTest(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="oas-config-")
        self.root = Path(self._temporary.name)
        (self.root / "config").mkdir()
        (self.root / "config" / "template.json").write_text("{}", encoding="utf-8")
        self.previous_cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.previous_cwd)
        self._temporary.cleanup()

    def test_config_names_cannot_escape_config_directory(self):
        self.assertFalse(ConfigManager.copy("../outside"))
        self.assertFalse(ConfigManager.copy("nested/name"))
        self.assertFalse(ConfigManager.rename("template", "../outside"))
        self.assertFalse(ConfigManager.delete("../outside"))
        self.assertFalse((self.root / "outside.json").exists())

    def test_delete_removes_config_without_permanent_unlink_api(self):
        self.assertTrue(ConfigManager.copy("oas1"))
        self.assertTrue(ConfigManager.delete("oas1"))
        self.assertFalse((self.root / "config" / "oas1.json").exists())


if __name__ == "__main__":
    unittest.main()
