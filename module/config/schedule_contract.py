from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ScheduleDecision:
    task: str
    when: datetime
    previous: datetime | None
    reason: str
    caller: str

