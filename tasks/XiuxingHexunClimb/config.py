from pydantic import Field

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.config_base import ConfigBase
from tasks.Component.config_scheduler import Scheduler


def _default_general_battle_config() -> GeneralBattleConfig:
    return GeneralBattleConfig(
        preset_enable=True,
        preset_group_name="每月活动",
        preset_team_name="爬塔222",
    )


class XiuxingHexunClimb(ConfigBase):
    """Temporary ticket-backed 日常训练 task used during 修行合训.

    ``max_challenges`` defaults to one so enabling the task for a live
    account is safe for the first test.  Set it to ``0`` when the event is
    ready to run until the right-side ticket counter reaches zero.
    """

    scheduler: Scheduler = Field(default_factory=Scheduler)
    max_challenges: int = Field(
        default=1,
        ge=0,
        # The temporary event provides a large ticket pool; keep a finite
        # upper bound while allowing the requested long unattended run.
        le=1000,
        title="Challenge Limit",
        description="0 means continue until the 日常训练 ticket counter reaches zero.",
    )
    activity_enabled: bool = Field(
        default=True,
        title="Activity Enabled",
        description="Disable this temporary activity without removing its configuration.",
    )
    general_battle_config: GeneralBattleConfig = Field(
        default_factory=_default_general_battle_config,
    )
