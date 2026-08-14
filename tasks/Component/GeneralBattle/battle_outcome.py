from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class BattleOutcome(str, Enum):
    NOT_STARTED = 'not_started'
    ACTIVE_UNCONFIRMED = 'active_unconfirmed'
    VICTORY = 'victory'
    DEFEAT = 'defeat'
    SETTLING = 'settling'
    RETURNED = 'returned'
    ABORTED = 'aborted'


@dataclass(frozen=True)
class BattleResult:
    outcome: BattleOutcome
    reason: str
    statistics: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.outcome in {BattleOutcome.VICTORY, BattleOutcome.RETURNED}

    def __bool__(self) -> bool:
        return self.success


def record_battle_result(
    owner: object,
    outcome: BattleOutcome,
    reason: str,
    **statistics: Any,
) -> BattleResult:
    result = BattleResult(outcome=outcome, reason=reason, statistics=statistics)
    setattr(owner, 'last_battle_result', result)
    return result
