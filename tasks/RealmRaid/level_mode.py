from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Iterable


class LevelMode(str, Enum):
    LOWER = 'lower'
    HOLD = 'hold'
    RAISE = 'raise'
    RECOVERY_HOLD = 'recovery_hold'


class LevelAction(str, Enum):
    OBSERVE = 'observe'
    SURRENDER = 'surrender'
    ATTACK = 'attack'
    REFRESH = 'refresh'
    WAIT_COOLDOWN = 'wait_cooldown'
    WAIT_AUTO_REFRESH = 'wait_auto_refresh'
    STOP = 'stop'
    UNSAFE = 'unsafe'


class PendingAction(str, Enum):
    NONE = 'none'
    SURRENDER = 'surrender'
    ATTACK = 'attack'
    REFRESH = 'refresh'


CHECKPOINT_CACHE_MAX_AGE_SECONDS = 900
CHECKPOINT_SCHEMA_VERSION = 3


class CheckpointError(RuntimeError):
    pass


class CheckpointLockTimeout(CheckpointError):
    pass


class CheckpointConflictError(CheckpointError):
    pass


class CheckpointCorruptError(CheckpointError):
    def __init__(self, message: str, quarantine_path: str | Path) -> None:
        super().__init__(message)
        self.quarantine_path = str(quarantine_path)


@contextmanager
def _cross_process_file_lock(path: Path, timeout: float, poll_interval: float = 0.05):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open('a+b')
    if path.stat().st_size == 0:
        handle.write(b'0')
        handle.flush()
    deadline = time.monotonic() + max(0.0, float(timeout))
    locked = False
    try:
        while not locked:
            handle.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise CheckpointLockTimeout(
                        f'timed out acquiring checkpoint lock: {path}'
                    )
                time.sleep(poll_interval)
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _int_tuple(values: Iterable[int]) -> tuple[int, ...]:
    return tuple(int(value) for value in values)


def _int_set(values: Iterable[int]) -> frozenset[int]:
    return frozenset(int(value) for value in values)


@dataclass(frozen=True)
class BoardSnapshot:
    levels: tuple[int, ...]
    challenge_level: int
    challenge_level_votes: int
    broken: frozenset[int] = field(default_factory=frozenset)
    failure_marked: frozenset[int] = field(default_factory=frozenset)
    attack_record: int | None = None
    tickets_current: int = 0
    tickets_total: int = 30
    refresh_available: bool = False
    refresh_cd_seconds: int | None = None
    layout_signature: str = ''
    level_source: str = 'ocr'
    captured_at: datetime = field(default_factory=datetime.now)
    imputed: frozenset[int] = field(default_factory=frozenset)

    def __post_init__(self):
        object.__setattr__(self, 'levels', _int_tuple(self.levels))
        object.__setattr__(self, 'broken', _int_set(self.broken))
        object.__setattr__(self, 'failure_marked', _int_set(self.failure_marked))
        object.__setattr__(self, 'imputed', _int_set(self.imputed))

    @property
    def valid_level_count(self) -> int:
        return sum(1 for level in self.levels if 1 <= level <= 60)

    @property
    def success_count(self) -> int:
        if self.attack_record is not None and 0 <= self.attack_record <= 9:
            return self.attack_record
        return len(self.broken)

    @property
    def attackable(self) -> frozenset[int]:
        return frozenset(range(1, 10)) - self.broken

    @property
    def evidence_conflict(self) -> bool:
        if self.attack_record is None:
            return False
        return self.attack_record != len(self.broken)

    def is_safe(self, min_valid_levels: int = 9, min_level_votes: int = 4) -> bool:
        if len(self.levels) != 9:
            return False
        if self.valid_level_count < min_valid_levels:
            return False
        if not 1 <= self.challenge_level <= 60:
            return False
        if self.challenge_level_votes < min_level_votes:
            return False
        if self.evidence_conflict:
            return False
        if not self.imputed.issubset(self.broken):
            return False
        if not 0 <= self.tickets_current <= max(self.tickets_total, 30):
            return False
        return True

    @property
    def board_signature(self) -> str:
        levels = ','.join(str(level) for level in self.levels)
        return self.layout_signature or f'levels:{levels}'


@dataclass
class RealmRaidCheckpoint:
    schema_version: int = CHECKPOINT_SCHEMA_VERSION
    revision: int = 0
    run_id: str = ''
    account: str = ''
    board_signature: str = ''
    mode: str = ''
    target_level: int = 59
    observed_level: int = 0
    observed_level_votes: int = 0
    observed_levels: tuple[int, ...] = field(default_factory=tuple)
    observed_broken: tuple[int, ...] = field(default_factory=tuple)
    observed_failure_marked: tuple[int, ...] = field(default_factory=tuple)
    failure_count: int = 0
    success_count: int = 0
    pending_action: str = PendingAction.NONE.value
    # For attack/surrender recovery, distinguish target selection from the
    # point after the battle transition. Older checkpoints default to
    # ``unknown`` and keep the conservative evidence-based recovery path.
    pending_stage: str = 'unknown'
    pending_success_before: int = 0
    pending_tickets_before: int = -1
    pending_failure_marked_before: bool = False
    pending_refresh: bool = False
    refresh_not_before: str = ''
    last_target: int = 0
    recovery_hold: bool = False
    updated_at: str = ''

    def __post_init__(self) -> None:
        self.observed_levels = _int_tuple(self.observed_levels)
        self.observed_broken = _int_tuple(self.observed_broken)
        self.observed_failure_marked = _int_tuple(self.observed_failure_marked)

    def remember_board(self, snapshot: BoardSnapshot) -> None:
        """Persist complete nine-cell evidence for the current board generation."""
        self.schema_version = CHECKPOINT_SCHEMA_VERSION
        self.board_signature = snapshot.board_signature
        self.observed_level = snapshot.challenge_level
        self.observed_level_votes = snapshot.challenge_level_votes
        self.observed_levels = snapshot.levels
        self.observed_broken = tuple(sorted(snapshot.broken))
        self.observed_failure_marked = tuple(sorted(snapshot.failure_marked))
        self.success_count = snapshot.success_count
        self.touch(snapshot.captured_at)

    def touch(self, now: datetime | None = None) -> None:
        self.updated_at = (now or datetime.now()).isoformat(timespec='seconds')

    def begin_action(
        self,
        action: PendingAction,
        snapshot: BoardSnapshot,
        target: int = 0,
    ) -> None:
        self.pending_action = action.value
        self.pending_stage = (
            'selection'
            if action in (PendingAction.ATTACK, PendingAction.SURRENDER)
            else 'action'
        )
        self.pending_success_before = snapshot.success_count
        self.pending_tickets_before = snapshot.tickets_current
        self.last_target = int(target)
        self.pending_failure_marked_before = target in snapshot.failure_marked
        self.touch(snapshot.captured_at)

    def finish_action(self) -> None:
        self.pending_action = PendingAction.NONE.value
        self.pending_stage = 'none'
        self.pending_success_before = 0
        self.pending_tickets_before = -1
        self.pending_failure_marked_before = False
        self.last_target = 0

    @property
    def level_mode(self) -> LevelMode | None:
        try:
            return LevelMode(self.mode)
        except ValueError:
            return None

    @property
    def refresh_due_at(self) -> datetime | None:
        if not self.refresh_not_before:
            return None
        try:
            return datetime.fromisoformat(self.refresh_not_before)
        except ValueError:
            return None

    @classmethod
    def from_dict(cls, data: dict) -> 'RealmRaidCheckpoint':
        supported = {item.name for item in cls.__dataclass_fields__.values()}
        values = {key: value for key, value in data.items() if key in supported}
        return cls(**values)


@dataclass(frozen=True)
class LevelDecision:
    mode: LevelMode | None
    action: LevelAction
    reason: str
    failure_count: int = 0
    success_count: int = 0


class CheckpointStore:
    def __init__(
        self,
        account: str,
        root: str | Path = './output/realm_raid_state',
        *,
        run_id: str | None = None,
        lock_timeout: float = 5.0,
    ):
        safe_account = re.sub(r'[^0-9A-Za-z_.-]+', '_', account).strip('._') or 'default'
        self.path = Path(root) / f'{safe_account}.json'
        self.lock_path = self.path.with_suffix(self.path.suffix + '.lock')
        self.run_id = str(run_id or uuid.uuid4().hex)
        self.lock_timeout = max(0.0, float(lock_timeout))

    @contextmanager
    def _locked(self):
        with _cross_process_file_lock(self.lock_path, self.lock_timeout):
            yield

    def _quarantine_unlocked(self, reason: str) -> Path:
        stamp = datetime.now().strftime('%Y%m%dT%H%M%S%f')
        quarantine = self.path.with_name(
            f'{self.path.stem}.corrupt.{stamp}.{uuid.uuid4().hex}{self.path.suffix}'
        )
        try:
            os.replace(self.path, quarantine)
        except OSError as error:
            raise CheckpointError(
                f'checkpoint is corrupt ({reason}) and quarantine failed: {error}'
            ) from error
        return quarantine

    def _load_unlocked(self) -> RealmRaidCheckpoint | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise TypeError('checkpoint root must be an object')
            checkpoint = RealmRaidCheckpoint.from_dict(data)
            if checkpoint.schema_version not in (1, 2, CHECKPOINT_SCHEMA_VERSION):
                raise ValueError(
                    f'unsupported checkpoint schema {checkpoint.schema_version}'
                )
            if checkpoint.revision < 0:
                raise ValueError('checkpoint revision cannot be negative')
            return checkpoint
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            quarantine = self._quarantine_unlocked(str(error))
            raise CheckpointCorruptError(
                f'checkpoint quarantined after validation failure: {error}',
                quarantine,
            ) from error
        except OSError as error:
            raise CheckpointError(f'checkpoint read failed: {error}') from error

    def load(self) -> RealmRaidCheckpoint | None:
        with self._locked():
            return self._load_unlocked()

    def save(self, checkpoint: RealmRaidCheckpoint) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked():
            current = self._load_unlocked()
            current_revision = 0 if current is None else current.revision
            if current is None and checkpoint.revision != 0:
                raise CheckpointConflictError(
                    'checkpoint was cleared after this copy was loaded'
                )
            if current is not None and checkpoint.revision != current_revision:
                raise CheckpointConflictError(
                    'checkpoint revision conflict: '
                    f'expected={checkpoint.revision}, current={current_revision}'
                )

            staged = replace(
                checkpoint,
                schema_version=CHECKPOINT_SCHEMA_VERSION,
                revision=current_revision + 1,
                run_id=self.run_id,
            )
            staged.touch()
            payload = json.dumps(asdict(staged), ensure_ascii=False, indent=2)
            temporary = self.path.with_name(
                f'{self.path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}'
            )
            try:
                with temporary.open('x', encoding='utf-8', newline='\n') as handle:
                    handle.write(payload + '\n')
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
                checkpoint.schema_version = staged.schema_version
                checkpoint.revision = staged.revision
                checkpoint.run_id = staged.run_id
                checkpoint.updated_at = staged.updated_at
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass

    def clear(self) -> None:
        with self._locked():
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def choose_level_mode(current_level: int, target_level: int) -> LevelMode:
    if current_level > target_level:
        return LevelMode.LOWER
    if current_level < target_level:
        return LevelMode.RAISE
    return LevelMode.HOLD


def cached_board_levels(
    checkpoint: RealmRaidCheckpoint | None,
    layout_signature: str,
    broken: Iterable[int] = (),
    failure_marked: Iterable[int] = (),
    now: datetime | None = None,
    max_age_seconds: int = CHECKPOINT_CACHE_MAX_AGE_SECONDS,
) -> tuple[int, ...]:
    """Return previously verified nine-cell levels only for the same board.

    The cache is rejected for old checkpoints, refresh transactions, incomplete
    evidence, signature changes, or a likely post-win generation reset.
    """
    if checkpoint is None or checkpoint.schema_version < 2:
        return ()
    if not layout_signature or checkpoint.board_signature != layout_signature:
        return ()
    if checkpoint.pending_refresh:
        return ()

    if now is not None:
        updated_at = checkpoint.updated_at
        try:
            age = (now - datetime.fromisoformat(updated_at)).total_seconds()
        except (TypeError, ValueError):
            return ()
        if age < 0 or age > max(0, int(max_age_seconds)):
            return ()

    expected_mode = choose_level_mode(checkpoint.observed_level, checkpoint.target_level)
    if (
        not checkpoint.recovery_hold
        and checkpoint.level_mode is not None
        and checkpoint.level_mode != expected_mode
    ):
        return ()

    broken_set = _int_set(broken)
    if checkpoint.success_count > 0 and not broken_set:
        return ()
    failure_set = _int_set(failure_marked)
    if checkpoint.failure_count > 0 and not broken_set and not failure_set:
        return ()
    if checkpoint.observed_broken and broken_set != _int_set(checkpoint.observed_broken):
        return ()
    if (
        checkpoint.observed_failure_marked
        and failure_set != _int_set(checkpoint.observed_failure_marked)
    ):
        return ()

    levels = _int_tuple(checkpoint.observed_levels)
    if len(levels) != 9 or any(not 1 <= level <= 60 for level in levels):
        return ()
    counts = Counter(levels)
    challenge_level, votes = max(counts.items(), key=lambda item: (item[1], item[0]))
    if challenge_level != checkpoint.observed_level:
        return ()
    if votes != checkpoint.observed_level_votes or votes < 4:
        return ()
    return levels


def checkpoint_matches(
    checkpoint: RealmRaidCheckpoint | None,
    snapshot: BoardSnapshot,
    target_level: int,
) -> bool:
    if checkpoint is None:
        return False
    if checkpoint.target_level != target_level:
        return False
    if checkpoint.observed_level != snapshot.challenge_level:
        return False
    if checkpoint.success_count > snapshot.success_count and not checkpoint.pending_refresh:
        return False
    expected_mode = choose_level_mode(snapshot.challenge_level, target_level)
    if (
        not checkpoint.recovery_hold
        and checkpoint.level_mode is not None
        and checkpoint.level_mode != expected_mode
    ):
        return False
    if checkpoint.board_signature and snapshot.board_signature:
        if checkpoint.board_signature != snapshot.board_signature:
            return False
    return True


def create_checkpoint(
    account: str,
    snapshot: BoardSnapshot,
    target_level: int,
    mode: LevelMode,
    recovery_hold: bool = False,
) -> RealmRaidCheckpoint:
    checkpoint = RealmRaidCheckpoint(
        account=account,
        mode=mode.value,
        target_level=target_level,
        failure_count=0,
        recovery_hold=recovery_hold,
    )
    checkpoint.remember_board(snapshot)
    return checkpoint


def reconcile_checkpoint(
    account: str,
    snapshot: BoardSnapshot,
    target_level: int,
    checkpoint: RealmRaidCheckpoint | None,
) -> RealmRaidCheckpoint:
    if checkpoint_matches(checkpoint, snapshot, target_level):
        checkpoint.remember_board(snapshot)
        return checkpoint

    partial_board = bool(snapshot.broken or snapshot.failure_marked or snapshot.success_count)
    if partial_board:
        replacement = create_checkpoint(
            account=account,
            snapshot=snapshot,
            target_level=target_level,
            mode=LevelMode.RECOVERY_HOLD,
            recovery_hold=True,
        )
    else:
        replacement = create_checkpoint(
            account=account,
            snapshot=snapshot,
            target_level=target_level,
            mode=choose_level_mode(snapshot.challenge_level, target_level),
        )
    if checkpoint is not None:
        replacement.revision = checkpoint.revision
        replacement.run_id = checkpoint.run_id
    return replacement


def decide_next_action(
    snapshot: BoardSnapshot,
    checkpoint: RealmRaidCheckpoint,
    min_valid_levels: int = 9,
    min_level_votes: int = 4,
) -> LevelDecision:
    mode = checkpoint.level_mode
    failures = max(0, checkpoint.failure_count)
    successes = snapshot.success_count

    if not snapshot.is_safe(min_valid_levels, min_level_votes):
        return LevelDecision(mode, LevelAction.UNSAFE, 'board evidence is not trustworthy', failures, successes)

    if checkpoint.pending_refresh:
        if snapshot.refresh_available:
            return LevelDecision(mode, LevelAction.REFRESH, 'pending manual refresh is available', failures, successes)
        return LevelDecision(mode, LevelAction.WAIT_COOLDOWN, 'manual refresh is still in cooldown', failures, successes)

    if snapshot.tickets_current <= 0:
        return LevelDecision(mode, LevelAction.STOP, 'no realm raid tickets', failures, successes)

    if mode == LevelMode.LOWER:
        if failures < 9:
            return LevelDecision(mode, LevelAction.SURRENDER, 'lowering requires nine failures', failures, successes)
        if snapshot.refresh_available:
            return LevelDecision(mode, LevelAction.REFRESH, 'nine failures reached', failures, successes)
        return LevelDecision(mode, LevelAction.WAIT_COOLDOWN, 'nine failures reached but refresh is cooling down', failures, successes)

    if mode in (LevelMode.HOLD, LevelMode.RECOVERY_HOLD):
        if failures < 4:
            return LevelDecision(mode, LevelAction.SURRENDER, 'holding requires four failures', failures, successes)
        if successes < 9:
            return LevelDecision(mode, LevelAction.ATTACK, 'holding requires nine wins', failures, successes)
        return LevelDecision(mode, LevelAction.WAIT_AUTO_REFRESH, 'nine wins reached; wait for automatic refresh', failures, successes)

    if mode == LevelMode.RAISE:
        if successes < 9:
            return LevelDecision(mode, LevelAction.ATTACK, 'raising uses wins without intentional surrender', failures, successes)
        return LevelDecision(mode, LevelAction.WAIT_AUTO_REFRESH, 'nine wins reached; wait for automatic refresh', failures, successes)

    return LevelDecision(mode, LevelAction.UNSAFE, 'checkpoint mode is invalid', failures, successes)


def schedule_after_cooldown(
    refresh_cd_seconds: int | None,
    now: datetime | None = None,
    safety_buffer_seconds: int = 10,
) -> datetime:
    current = now or datetime.now()
    seconds = max(0, int(refresh_cd_seconds or 0)) + max(0, safety_buffer_seconds)
    return current + timedelta(seconds=seconds)


def generation_changed(before: BoardSnapshot, after: BoardSnapshot) -> bool:
    if after.challenge_level != before.challenge_level:
        return True
    if after.success_count < before.success_count:
        return True
    if before.success_count >= 8 and after.success_count == 0 and not after.broken:
        return True
    if before.layout_signature and after.layout_signature:
        if before.layout_signature != after.layout_signature and after.success_count == 0:
            return True
    return False
