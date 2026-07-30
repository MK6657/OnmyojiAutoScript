from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any

from .models import AccountMetadata


class MetadataRepository:
    """存放纯界面数据；任务参数的事实来源永远是 OAS Core。

    这里额外承担了模板和任务显示顺序的持久化。放在 Bridge 而不是浏览器
    localStorage，是为了让它们能随 Bridge 数据库一起备份、换机器不丢。
    """

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS account_metadata (
                    account_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    avatar TEXT NOT NULL DEFAULT 'blue',
                    tags TEXT NOT NULL DEFAULT '',
                    device_label TEXT NOT NULL DEFAULT '未配置设备',
                    sort_order INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS config_template (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    task_title TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    payload TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_order (
                    account_id TEXT PRIMARY KEY,
                    task_ids TEXT NOT NULL DEFAULT '[]'
                )
                """
            )

    # ------------------------------------------------------------- 账号元数据

    @staticmethod
    def _from_row(row: sqlite3.Row) -> AccountMetadata:
        tags = [tag for tag in (row["tags"] or "").split(",") if tag]
        return AccountMetadata(
            id=row["account_id"],
            name=row["name"],
            avatar=row["avatar"],
            tags=tags,
            device_label=row["device_label"],
            sort_order=row["sort_order"],
        )

    def sync_accounts(self, account_ids: list[str]) -> list[AccountMetadata]:
        with self._lock, self._connect() as connection:
            existing = {
                row["account_id"]: self._from_row(row)
                for row in connection.execute("SELECT * FROM account_metadata")
            }
            for index, account_id in enumerate(account_ids):
                if account_id not in existing:
                    metadata = AccountMetadata(id=account_id, name=account_id, sort_order=index)
                    connection.execute(
                        "INSERT INTO account_metadata(account_id, name, avatar, tags, device_label, sort_order)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (metadata.id, metadata.name, metadata.avatar, "", metadata.device_label, metadata.sort_order),
                    )
                    existing[account_id] = metadata
            stale = set(existing) - set(account_ids)
            for account_id in stale:
                connection.execute("DELETE FROM account_metadata WHERE account_id = ?", (account_id,))
                connection.execute("DELETE FROM task_order WHERE account_id = ?", (account_id,))
                existing.pop(account_id, None)
            return sorted((existing[item] for item in account_ids), key=lambda item: (item.sort_order, item.id))

    def get(self, account_id: str) -> AccountMetadata | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM account_metadata WHERE account_id = ?", (account_id,)
            ).fetchone()
            return self._from_row(row) if row else None

    def upsert(self, metadata: AccountMetadata) -> AccountMetadata:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO account_metadata(account_id, name, avatar, tags, device_label, sort_order)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    name=excluded.name,
                    avatar=excluded.avatar,
                    tags=excluded.tags,
                    device_label=excluded.device_label,
                    sort_order=excluded.sort_order
                """,
                (metadata.id, metadata.name, metadata.avatar, ",".join(metadata.tags), metadata.device_label, metadata.sort_order),
            )
            return metadata

    def rename(self, old_id: str, metadata: AccountMetadata) -> AccountMetadata:
        """重命名账号时把旧行一并迁移，避免数据库里留下再也不会被清掉的孤儿记录。"""
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM account_metadata WHERE account_id = ?", (metadata.id,))
            connection.execute(
                "UPDATE account_metadata SET account_id = ?, name = ?, avatar = ?, tags = ?, device_label = ?, sort_order = ?"
                " WHERE account_id = ?",
                (metadata.id, metadata.name, metadata.avatar, ",".join(metadata.tags),
                 metadata.device_label, metadata.sort_order, old_id),
            )
            connection.execute("UPDATE task_order SET account_id = ? WHERE account_id = ?", (metadata.id, old_id))
            return metadata

    def delete(self, account_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM account_metadata WHERE account_id = ?", (account_id,))
            connection.execute("DELETE FROM task_order WHERE account_id = ?", (account_id,))

    # ----------------------------------------------------------------- 模板

    def templates(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM config_template ORDER BY created_at DESC").fetchall()
        result = []
        for row in rows:
            try:
                groups = json.loads(row["payload"])
            except (TypeError, ValueError):
                groups = {}
            result.append({
                "id": row["id"], "name": row["name"], "task_id": row["task_id"],
                "task_title": row["task_title"], "created_at": row["created_at"], "groups": groups,
            })
        return result

    def save_template(self, template: dict[str, Any]) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO config_template(id, name, task_id, task_title, created_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, task_id=excluded.task_id,
                    task_title=excluded.task_title, payload=excluded.payload
                """,
                (
                    template["id"], template.get("name", ""), template.get("task_id", ""),
                    template.get("task_title", ""), template.get("created_at", ""),
                    json.dumps(template.get("groups", {}), ensure_ascii=False),
                ),
            )
        return template

    def delete_template(self, template_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM config_template WHERE id = ?", (template_id,))

    # ------------------------------------------------------------ 显示顺序

    def task_order(self, account_id: str) -> list[str]:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT task_ids FROM task_order WHERE account_id = ?", (account_id,)).fetchone()
        if not row:
            return []
        try:
            value = json.loads(row["task_ids"])
            return [str(item) for item in value] if isinstance(value, list) else []
        except (TypeError, ValueError):
            return []

    def save_task_order(self, account_id: str, order: list[str]) -> list[str]:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO task_order(account_id, task_ids) VALUES (?, ?)"
                " ON CONFLICT(account_id) DO UPDATE SET task_ids=excluded.task_ids",
                (account_id, json.dumps(order, ensure_ascii=False)),
            )
        return order
