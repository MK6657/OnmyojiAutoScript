from dataclasses import dataclass, field
from enum import Enum


class FailureAction(str, Enum):
    """How a task result changes the scheduler's consecutive-failure count."""

    RESET = 'reset'
    INCREMENT = 'increment'
    PRESERVE = 'preserve'


@dataclass(frozen=True)
class TaskExecutionResult:
    """Structured task result with backward-compatible truthiness."""

    outcome: str
    reason: str
    statistics: dict = field(default_factory=dict)
    next_run: object = None
    failure_action: FailureAction = FailureAction.INCREMENT

    SUCCESS_OUTCOMES = frozenset({'victory', 'returned'})

    @property
    def success(self) -> bool:
        return self.outcome in self.SUCCESS_OUTCOMES

    def __bool__(self) -> bool:
        return self.success

    def next_failure_count(self, previous: int) -> int:
        previous = max(0, int(previous))
        if self.failure_action is FailureAction.RESET:
            return 0
        if self.failure_action is FailureAction.INCREMENT:
            return previous + 1
        return previous

    @classmethod
    def completed(cls, reason: str, **kwargs) -> 'TaskExecutionResult':
        return cls(
            outcome=str(kwargs.pop('outcome', 'returned')),
            reason=reason,
            failure_action=FailureAction.RESET,
            **kwargs,
        )

    @classmethod
    def deferred(cls, reason: str, **kwargs) -> 'TaskExecutionResult':
        return cls(
            outcome='deferred',
            reason=reason,
            failure_action=FailureAction.PRESERVE,
            **kwargs,
        )

    @classmethod
    def stopped(cls, reason: str, **kwargs) -> 'TaskExecutionResult':
        return cls(
            outcome='stopped',
            reason=reason,
            failure_action=FailureAction.PRESERVE,
            **kwargs,
        )

    @classmethod
    def failed(cls, reason: str, **kwargs) -> 'TaskExecutionResult':
        return cls(
            outcome=str(kwargs.pop('outcome', 'failed')),
            reason=reason,
            failure_action=FailureAction.INCREMENT,
            **kwargs,
        )

    @classmethod
    def from_task_end(cls, error: 'TaskEnd') -> 'TaskExecutionResult':
        return cls(
            outcome=error.outcome,
            reason=error.reason,
            statistics=error.statistics,
            next_run=error.next_run,
            failure_action=error.failure_action,
        )

    @classmethod
    def coerce(cls, value) -> 'TaskExecutionResult':
        if isinstance(value, cls):
            return value
        if value is True:
            return cls.completed('legacy successful task result')
        return cls.failed('legacy failed task result')


class CampaignEnd(Exception):
    pass


class MapDetectionError(Exception):
    pass


class MapWalkError(Exception):
    pass


class MapEnemyMoved(Exception):
    pass


class CampaignNameError(Exception):
    pass


class ScriptError(Exception):
    # This is likely to be a mistake of developers, but sometimes a random issue
    pass


class ScriptEnd(Exception):
    pass


class GameStuckError(Exception):
    pass


class GameBugError(Exception):
    # An error has occurred in Azur Lane game client. Alas is unable to handle.
    # A restart should fix it.
    pass


class GameTooManyClickError(Exception):
    pass


class EmulatorNotRunningError(Exception):
    pass


class GameNotRunningError(Exception):
    pass


class GamePageUnknownError(Exception):
    pass


class RequestHumanTakeover(Exception):
    # Request human takeover
    # Alas is unable to handle such error, probably because of wrong settings.
    pass

class TaskEnd(Exception):
    """Structured task termination signal.

    A bare ``TaskEnd`` is intentionally an aborted task. Callers must use
    :meth:`completed` when the scheduler may count the task as successful.
    """

    SUCCESS_OUTCOMES = TaskExecutionResult.SUCCESS_OUTCOMES
    PRESERVE_OUTCOMES = frozenset({'deferred', 'paused', 'stopped'})

    def __init__(
        self,
        message: str | None = None,
        *,
        outcome: str = 'aborted',
        reason: str | None = None,
        statistics: dict | None = None,
        next_run=None,
        failure_action: FailureAction | str | None = None,
    ) -> None:
        resolved_reason = reason if reason is not None else (message or 'task aborted')
        super().__init__(resolved_reason)
        self.outcome = str(outcome)
        self.reason = str(resolved_reason)
        self.statistics = dict(statistics or {})
        self.next_run = next_run
        if failure_action is None:
            if self.outcome in self.SUCCESS_OUTCOMES:
                failure_action = FailureAction.RESET
            elif self.outcome in self.PRESERVE_OUTCOMES:
                failure_action = FailureAction.PRESERVE
            else:
                failure_action = FailureAction.INCREMENT
        self.failure_action = FailureAction(failure_action)

    @property
    def success(self) -> bool:
        return self.outcome in self.SUCCESS_OUTCOMES

    @classmethod
    def completed(
        cls,
        reason: str,
        *,
        outcome: str = 'returned',
        statistics: dict | None = None,
        next_run=None,
    ) -> 'TaskEnd':
        if outcome not in cls.SUCCESS_OUTCOMES:
            raise ValueError(f'completed TaskEnd cannot use outcome={outcome!r}')
        return cls(
            outcome=outcome,
            reason=reason,
            statistics=statistics,
            next_run=next_run,
            failure_action=FailureAction.RESET,
        )

    @classmethod
    def deferred(
        cls,
        reason: str,
        *,
        statistics: dict | None = None,
        next_run=None,
    ) -> 'TaskEnd':
        return cls(
            outcome='deferred',
            reason=reason,
            statistics=statistics,
            next_run=next_run,
            failure_action=FailureAction.PRESERVE,
        )

    @classmethod
    def stopped(
        cls,
        reason: str,
        *,
        statistics: dict | None = None,
        next_run=None,
    ) -> 'TaskEnd':
        return cls(
            outcome='stopped',
            reason=reason,
            statistics=statistics,
            next_run=next_run,
            failure_action=FailureAction.PRESERVE,
        )

    @classmethod
    def failed(
        cls,
        reason: str,
        *,
        outcome: str = 'failed',
        statistics: dict | None = None,
        next_run=None,
    ) -> 'TaskEnd':
        if outcome in cls.SUCCESS_OUTCOMES or outcome in cls.PRESERVE_OUTCOMES:
            raise ValueError(f'failed TaskEnd cannot use outcome={outcome!r}')
        return cls(
            outcome=outcome,
            reason=reason,
            statistics=statistics,
            next_run=next_run,
            failure_action=FailureAction.INCREMENT,
        )

    @classmethod
    def aborted(
        cls,
        reason: str,
        *,
        outcome: str = 'aborted',
        statistics: dict | None = None,
        next_run=None,
    ) -> 'TaskEnd':
        if outcome in cls.SUCCESS_OUTCOMES:
            raise ValueError(f'aborted TaskEnd cannot use outcome={outcome!r}')
        return cls(
            outcome=outcome,
            reason=reason,
            statistics=statistics,
            next_run=next_run,
        )
