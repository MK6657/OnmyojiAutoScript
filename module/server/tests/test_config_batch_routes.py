import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from module.server.script_router import (
    ConfigBatchPatch,
    script_config_revision,
    script_set_value,
    script_set_values,
)


class ConfigBatchRouteTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup)
        self.previous = Path.cwd()
        root = Path(self.temp.name)
        (root / "config").mkdir()
        shutil.copy2(self.previous / "config" / "oas1.json", root / "config" / "oas1.json")
        os.chdir(root)

    async def _cleanup(self):
        os.chdir(self.previous)
        self.temp.cleanup()

    def read(self):
        return json.loads(Path("config/oas1.json").read_text(encoding="utf-8"))

    async def test_batch_route_updates_all_fields_once(self):
        revision = (await script_config_revision("oas1"))["revision"]
        result = await script_set_values(
            "oas1",
            "RyouToppa",
            ConfigBatchPatch(
                expected_revision=revision,
                fields=[
                    {"group": "raid_config", "name": "limit_count", "value": 17, "type": "integer"},
                    {"group": "raid_config", "name": "random_delay", "value": True, "type": "boolean"},
                    {"group": "raid_config", "name": "auto_select_highest_guild", "value": False, "type": "boolean"},
                ],
            ),
        )

        data = self.read()
        self.assertTrue(result["saved"])
        self.assertEqual(result["updated"], 3)
        self.assertEqual(data["ryou_toppa"]["raid_config"]["limit_count"], 17)
        self.assertTrue(data["ryou_toppa"]["raid_config"]["random_delay"])
        self.assertFalse(data["ryou_toppa"]["raid_config"]["auto_select_highest_guild"])

    async def test_batch_route_updates_scalar_task_controls(self):
        revision = (await script_config_revision("oas1"))["revision"]
        result = await script_set_values(
            "oas1",
            "XiuxingHexun",
            ConfigBatchPatch(
                expected_revision=revision,
                fields=[
                    {"group": "max_challenges", "name": "max_challenges", "value": 1, "type": "integer"},
                    {"group": "activity_enabled", "name": "activity_enabled", "value": True, "type": "boolean"},
                ],
            ),
        )

        data = self.read()
        self.assertTrue(result["saved"])
        self.assertGreaterEqual(result["updated"], 2)
        self.assertEqual(data["xiuxing_hexun"]["max_challenges"], 1)
        self.assertTrue(data["xiuxing_hexun"]["activity_enabled"])

    async def test_batch_update_preserves_disabled_state_and_extensions(self):
        data = self.read()
        data["xiuxing_hexun"]["activity_enabled"] = False
        data["xiuxing_hexun"]["max_challenges"] = 3
        data["custom_plugin_root"] = {"preserve_me": 1}
        data["xiuxing_hexun"]["custom_plugin_nested"] = "preserve_me"
        Path("config/oas1.json").write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8",
        )
        revision = (await script_config_revision("oas1"))["revision"]

        await script_set_values(
            "oas1",
            "XiuxingHexun",
            ConfigBatchPatch(
                expected_revision=revision,
                fields=[{
                    "group": "general_battle_config",
                    "name": "preset_team_name",
                    "value": "【修行合训】测试",
                    "type": "string",
                }],
            ),
        )

        saved = self.read()
        self.assertFalse(saved["xiuxing_hexun"]["activity_enabled"])
        self.assertEqual(saved["xiuxing_hexun"]["max_challenges"], 3)
        self.assertEqual(saved["custom_plugin_root"], {"preserve_me": 1})
        self.assertEqual(
            saved["xiuxing_hexun"]["custom_plugin_nested"],
            "preserve_me",
        )

    async def test_legacy_value_route_migrates_missing_task_parent(self):
        data = self.read()
        data.pop("xiuxing_hexun", None)
        Path("config/oas1.json").write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8",
        )

        revision = (await script_config_revision("oas1"))["revision"]
        result = await script_set_value(
            "oas1",
            "XiuxingHexun",
            "max_challenges",
            "max_challenges",
            "integer",
            "3",
            if_match=revision,
        )

        self.assertTrue(result)
        saved = self.read()
        self.assertEqual(saved["xiuxing_hexun"]["max_challenges"], 3)
        self.assertEqual(
            saved["xiuxing_hexun"]["general_battle_config"]["preset_team_name"],
            "【修行合训】顶配",
        )

    async def test_global_activity_gate_rejects_enable(self):
        revision = (await script_config_revision("oas1"))["revision"]
        with patch.dict(
            os.environ,
            {"OAS_XIUXING_HEXUN_ENABLED": "0"},
        ):
            with self.assertRaises(HTTPException) as caught:
                await script_set_values(
                    "oas1",
                    "XiuxingHexun",
                    ConfigBatchPatch(
                        expected_revision=revision,
                        fields=[{
                            "group": "scheduler",
                            "name": "enable",
                            "value": True,
                            "type": "boolean",
                        }],
                    ),
                )

        self.assertEqual(caught.exception.status_code, 409)

    async def test_stale_revision_returns_409_and_does_not_write(self):
        revision = (await script_config_revision("oas1"))["revision"]
        await script_set_values(
            "oas1",
            "RyouToppa",
            ConfigBatchPatch(
                expected_revision=revision,
                fields=[{"group": "raid_config", "name": "limit_count", "value": 17, "type": "integer"}],
            ),
        )
        before = Path("config/oas1.json").read_bytes()

        with self.assertRaises(HTTPException) as caught:
            await script_set_values(
                "oas1",
                "RyouToppa",
                ConfigBatchPatch(
                    expected_revision=revision,
                    fields=[{"group": "raid_config", "name": "limit_count", "value": 18, "type": "integer"}],
                ),
            )

        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(Path("config/oas1.json").read_bytes(), before)

    async def test_missing_revision_returns_428_and_does_not_write(self):
        before = Path("config/oas1.json").read_bytes()

        with self.assertRaises(HTTPException) as caught:
            await script_set_values(
                "oas1",
                "RyouToppa",
                ConfigBatchPatch(
                    fields=[{"group": "raid_config", "name": "limit_count", "value": 18, "type": "integer"}],
                ),
            )

        self.assertEqual(caught.exception.status_code, 428)
        self.assertEqual(Path("config/oas1.json").read_bytes(), before)

    async def test_if_match_header_can_supply_revision(self):
        revision = (await script_config_revision("oas1"))["revision"]

        result = await script_set_values(
            "oas1",
            "RyouToppa",
            ConfigBatchPatch(
                fields=[{"group": "raid_config", "name": "limit_count", "value": 19, "type": "integer"}],
            ),
            if_match=f'"{revision}"',
        )

        self.assertTrue(result["saved"])
        self.assertEqual(self.read()["ryou_toppa"]["raid_config"]["limit_count"], 19)
    def _concurrent_put_race(self, task, group, argument, winner_values):
        import asyncio as aio
        import threading

        revision = aio.run(script_config_revision("oas1"))["revision"]
        barrier = threading.Barrier(2)
        results = []

        def worker(worker_id, value):
            async def run():
                barrier.wait()
                try:
                    await script_set_value(
                        "oas1", task, group, argument, "integer", str(value),
                        if_match=revision,
                    )
                    return "ok"
                except HTTPException as error:
                    return f"http-{error.status_code}"
                except Exception as error:
                    return f"err-{type(error).__name__}"

            results.append((worker_id, aio.run(run())))

        threads = [
            threading.Thread(target=worker, args=(0, winner_values[0])),
            threading.Thread(target=worker, args=(1, winner_values[1])),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return results

    def test_concurrent_put_xiuxing_same_revision_one_wins(self):
        results = self._concurrent_put_race(
            "XiuxingHexun", "max_challenges", "max_challenges", (41, 42)
        )
        statuses = sorted(status for _, status in results)
        self.assertEqual(statuses, ["http-409", "ok"])
        saved = self.read()
        self.assertIn(saved["xiuxing_hexun"]["max_challenges"], (41, 42))

    def test_concurrent_put_legacy_task_same_revision_one_wins(self):
        results = self._concurrent_put_race(
            "RyouToppa", "raid_config", "limit_count", (21, 22)
        )
        statuses = sorted(status for _, status in results)
        self.assertEqual(statuses, ["http-409", "ok"])
        saved = self.read()
        self.assertIn(saved["ryou_toppa"]["raid_config"]["limit_count"], (21, 22))



if __name__ == "__main__":
    unittest.main()
