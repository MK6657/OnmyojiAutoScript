import json
import os
import tempfile
import unittest
from pathlib import Path

from module.config.config_transaction import (
    ConfigRevisionConflict,
    apply_json_patch,
    file_revision,
    merge_changed_json,
)
from module.config.config_model import ConfigModel


class ConfigTransactionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "account.json"
        self.path.write_text(
            json.dumps({"task": {"scheduler": {"enable": False, "priority": 1}, "raid": {"count": 10}}}),
            encoding="utf-8",
        )

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_batch_patch_is_all_or_nothing(self):
        before = file_revision(self.path)

        result = apply_json_patch(
            self.path,
            [
                (("task", "scheduler", "enable"), True),
                (("task", "scheduler", "priority"), 8),
                (("task", "raid", "count"), 30),
            ],
            expected_revision=before,
        )

        self.assertNotEqual(result.revision, before)
        self.assertEqual(self.read()["task"]["scheduler"], {"enable": True, "priority": 8})
        self.assertEqual(self.read()["task"]["raid"]["count"], 30)

    def test_invalid_field_rolls_back_entire_batch(self):
        before_text = self.path.read_text(encoding="utf-8")

        with self.assertRaises(KeyError):
            apply_json_patch(
                self.path,
                [
                    (("task", "scheduler", "priority"), 8),
                    (("task", "missing", "field"), 30),
                ],
            )

        self.assertEqual(self.path.read_text(encoding="utf-8"), before_text)

    def test_stale_revision_is_rejected(self):
        stale = file_revision(self.path)
        apply_json_patch(
            self.path,
            [(("task", "scheduler", "priority"), 2)],
            expected_revision=stale,
        )

        with self.assertRaises(ConfigRevisionConflict):
            apply_json_patch(
                self.path,
                [(("task", "scheduler", "priority"), 3)],
                expected_revision=stale,
            )

        self.assertEqual(self.read()["task"]["scheduler"]["priority"], 2)

    def test_stale_worker_merges_only_its_changed_fields(self):
        baseline = self.read()
        ui = json.loads(json.dumps(baseline))
        worker = json.loads(json.dumps(baseline))
        ui["task"]["scheduler"]["priority"] = 9
        worker["task"]["raid"]["count"] = 22
        apply_json_patch(
            self.path,
            [(("task", "scheduler", "priority"), 9)],
            expected_revision=file_revision(self.path),
        )

        result = merge_changed_json(self.path, baseline, worker)

        self.assertEqual(result.data["task"]["scheduler"]["priority"], 9)
        self.assertEqual(result.data["task"]["raid"]["count"], 22)

    def test_stale_workers_cannot_overwrite_the_same_leaf(self):
        baseline = self.read()
        first = json.loads(json.dumps(baseline))
        second = json.loads(json.dumps(baseline))
        first["task"]["scheduler"]["priority"] = 8
        second["task"]["scheduler"]["priority"] = 9
        merge_changed_json(self.path, baseline, first)

        with self.assertRaises(ConfigRevisionConflict):
            merge_changed_json(self.path, baseline, second)

        self.assertEqual(self.read()["task"]["scheduler"]["priority"], 8)

    def test_config_model_stale_instances_preserve_unrelated_updates(self):
        root = Path(self.temp.name)
        config_dir = root / "config"
        config_dir.mkdir(exist_ok=True)
        account = config_dir / "concurrent.json"
        defaults = ConfigModel().model_dump()
        defaults["config_name"] = "concurrent"
        account.write_text(
            json.dumps(defaults, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        previous = Path.cwd()
        os.chdir(root)
        self.addCleanup(os.chdir, previous)
        ui_model = ConfigModel(config_name="concurrent")
        worker_model = ConfigModel(config_name="concurrent")

        ui_model.realm_raid.scheduler.priority = 11
        ui_model.save()
        worker_model.ryou_toppa.raid_config.limit_count = 22
        worker_model.save()

        final = json.loads(account.read_text(encoding="utf-8"))
        self.assertEqual(final["realm_raid"]["scheduler"]["priority"], 11)
        self.assertEqual(final["ryou_toppa"]["raid_config"]["limit_count"], 22)


if __name__ == "__main__":
    unittest.main()
