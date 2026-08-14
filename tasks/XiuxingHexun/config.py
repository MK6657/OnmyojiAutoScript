from pydantic import Field

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.config_base import ConfigBase
from tasks.Component.config_scheduler import Scheduler


def _default_general_battle_config() -> GeneralBattleConfig:
    return GeneralBattleConfig(
        preset_enable=True,
        preset_group_name="每月活动",
        preset_team_name="【修行合训】顶配",
    )


class XiuxingHexun(ConfigBase):
    """Configuration for the limited-time 修行合训 activity.

    The task has no calendar gate. The scheduler controls when it is run;
    the activity page and ticket marker control whether another challenge is
    available.
    """

    scheduler: Scheduler = Field(default_factory=Scheduler)
    max_challenges: int = Field(
        default=0,
        ge=0,
        le=100,
        title="Challenge Limit",
        description="0 means continue until the activity reports no tickets.",
    )
    activity_enabled: bool = Field(
        default=True,
        title="Activity Enabled",
        description="Disable this activity for the current account without deleting its configuration.",
    )
    general_battle_config: GeneralBattleConfig = Field(
        default_factory=_default_general_battle_config,
    )
