from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AccountMetadata(BaseModel):
    id: str
    name: str
    avatar: str = "blue"
    tags: list[str] = Field(default_factory=list)
    device_label: str = "未配置设备"
    sort_order: int = 0


class AccountView(AccountMetadata):
    state: str = "offline"
    state_label: str = "离线"
    connected: bool = False
    selected_count: int = 0
    selected_tasks: list[str] = Field(default_factory=list)
    next_run: str | None = None


class TaskSummary(BaseModel):
    id: str
    title: str
    category: str
    enabled: bool = False
    next_run: str | None = None
    available: bool = True


class ConfigField(BaseModel):
    name: str
    title: str
    description: str = ""
    default: Any = None
    value: Any = None
    type: str
    options: list[Any] = Field(default_factory=list)


class TaskConfig(BaseModel):
    task_id: str
    title: str
    groups: dict[str, list[ConfigField]]


class ConfigPatchField(BaseModel):
    group: str
    name: str
    value: Any
    type: str | None = None


class ConfigPatch(BaseModel):
    fields: list[ConfigPatchField] = Field(default_factory=list)


class AccountCreate(BaseModel):
    name: str | None = None
    device_label: str = "未配置设备"
    avatar: str = "blue"
    tags: list[str] = Field(default_factory=list)


class AccountPatch(BaseModel):
    name: str | None = None
    device_label: str | None = None
    avatar: str | None = None
    tags: list[str] | None = None
    sort_order: int | None = None


class AccountAction(BaseModel):
    action: Literal["start", "stop", "restart", "refresh"]


class TemplatePayload(BaseModel):
    """界面侧的配置模板。Bridge 只负责存取，不解释里面的字段含义。"""

    id: str
    name: str = ""
    task_id: str = ""
    task_title: str = ""
    created_at: str = ""
    groups: dict[str, Any] = Field(default_factory=dict)


class TaskOrderPatch(BaseModel):
    order: list[str] = Field(default_factory=list)
