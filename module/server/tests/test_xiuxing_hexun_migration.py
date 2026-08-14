import json
import tempfile
import unittest
from pathlib import Path

from module.config.config_model import ConfigModel
from module.config.config_transaction import apply_json_patch, file_revision
from module.server.script_router import (
    _missing_task_parent_updates,
    _validate_config_preserving_unknown,
)


class XiuxingHexunConfigMigrationTest(unittest.TestCase):
    def test_missing_task_parent_is_explicitly_created(self):
        model = ConfigModel()
        updates = _missing_task_parent_updates(
            {"running_task": ""},
            model,
            "xiuxing_hexun",
        )

        self.assertEqual([path for path, _value in updates], [("xiuxing_hexun",)])
        self.assertEqual(
            updates[0][1]["general_battle_config"]["preset_team_name"],
            "【修行合训】顶配",
        )

    def test_partial_task_parent_gets_missing_groups_without_overwrite(self):
        model = ConfigModel()
        raw = {
            "xiuxing_hexun": {
                "activity_enabled": False,
                "max_challenges": 3,
            }
        }
        updates = _missing_task_parent_updates(raw, model, "xiuxing_hexun")
        paths = [path for path, _value in updates]

        self.assertIn(("xiuxing_hexun", "scheduler"), paths)
        self.assertIn(("xiuxing_hexun", "general_battle_config"), paths)
        self.assertNotIn(("xiuxing_hexun",), paths)
        self.assertNotIn(("xiuxing_hexun", "activity_enabled"), paths)
        self.assertNotIn(("xiuxing_hexun", "max_challenges"), paths)

    def test_parent_and_field_are_written_in_one_revision(self):
        model = ConfigModel()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oas1.json"
            path.write_text(json.dumps({"running_task": ""}), encoding="utf-8")
            raw = json.loads(path.read_text(encoding="utf-8"))
            migration = _missing_task_parent_updates(raw, model, "xiuxing_hexun")
            result = apply_json_patch(
                path,
                migration + [
                    (("xiuxing_hexun", "max_challenges"), 3),
                ],
                expected_revision=file_revision(path),
                validator=_validate_config_preserving_unknown,
                allow_new_leaf=True,
            )
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(saved["xiuxing_hexun"]["max_challenges"], 3)
        self.assertEqual(result.changed_paths[0], ("xiuxing_hexun",))
        self.assertEqual(result.changed_paths[-1], ("xiuxing_hexun", "max_challenges"))

    def test_validator_preserves_unknown_extension_fields(self):
        data = ConfigModel().model_dump()
        data["custom_plugin_root"] = {"preserve_me": 1}
        data["xiuxing_hexun"]["custom_plugin_nested"] = "preserve_me"

        validated = _validate_config_preserving_unknown(data)

        self.assertEqual(validated["custom_plugin_root"], {"preserve_me": 1})
        self.assertEqual(
            validated["xiuxing_hexun"]["custom_plugin_nested"],
            "preserve_me",
        )


if __name__ == "__main__":
    unittest.main()
