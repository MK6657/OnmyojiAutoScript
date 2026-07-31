from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
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


def _int_tuple(values: Iterable[int]) -> tuple[int, ...]:
    return tuple(int(value) for value in values)


def _int_set(values: Iterable[int]) -> frozenset[int]:
    return frozenset(int(value) for value in values)


def resolve_broken_levels(
    levels: Iterable[int],
    broken: Iterable[int],
    expected_level: int = 0,
    min_observed_levels: int = 4,
    min_observed_votes: int = 4,
) -> tuple[tuple[int, ...], frozenset[int], str]:
    """Replace unreliable OCR from broken cards with trusted board-level evidence.

    Broken cards are visually dimmed by the game, so their level plaques cannot be
    treated as normal OCR input. A fresh partial board needs at least four visible
    unbroken cards agreeing on the mode. Once a checkpoint exists, the caller may
    provide its expected level after separately confirming the board signature.
    """
    raw = _int_tuple(levels)
    broken_set = _int_set(broken)
    if len(raw) != 9 or not broken_set:
        return raw, frozenset(), ''
    if any(index < 1 or index > len(raw) for index in broken_set):
        return raw, frozenset(), ''

    unbroken = [
        level for index, level in enumerate(raw, start=1)
        if index not in broken_set
    ]
    if any(not 1 <= level <= 60 for level in unbroken):
        return raw, frozenset(), ''

    if 1 <= int(expected_level or 0) <= 60:
        challenge_level = int(expected_level)
        source = 'checkpoint'
    else:
        if len(unbroken) < min_observed_levels:
            return raw, frozenset(), ''
        counts = Counter(unbroken)
        challenge_level, votes = max(counts.items(), key=lambda item: (item[1], item[0]))
        if votes < min_observed_votes:
            return raw, frozenset(), ''
        source = 'visible-unbroken'

    resolved = list(raw)
    for index in broken_set:
        resolved[index - 1] = challenge_level
    return tuple(resolved), broken_set, source


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

    def is_safe(self, min_valid_levels: int = 6, min_level_votes: int = 4) -> bool:
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
    schema_version: int = 1
    account: str = ''
    board_signature: str = ''
    mode: str = ''
    target_level: int = 59
    observed_level: int = 0
    failure_count: int = 0
    success_count: int = 0
    pending_action: str = PendingAction.NONE.value
    pending_success_before: int = 0
    pending_tickets_before: int = -1
    pending_failure_marked_before: bool = False
    pending_refresh: bool = False
    refresh_not_before: str = ''
    last_target: int = 0
    recovery_hold: bool = False
    updated_at: str = ''

    def touch(self, now: datetime | None = None) -> None:
        self.updated_at = (now or datetime.now()).isoformat(timespec='seconds')

    def begin_action(
        self,
        action: PendingAction,
        snapshot: BoardSnapshot,
        target: int = 0,
    ) -> None:
        self.pending_action = action.value
        self.pending_success_before = snapshot.success_count
        self.pending_tickets_before = snapshot.tickets_current
        self.last_target = int(target)
        self.pending_failure_marked_before = target in snapshot.failure_marked
        self.touch(snapshot.captured_at)

    def finish_action(self) -> None:
        self.pending_action = PendingAction.NONE.value
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
    def __init__(self, account: str, root: str | Path = './output/realm_raid_state'):
        safe_account = re.sub(r'[^0-9A-Za-z_.-]+', '_', account).strip('._') or 'default'
        self.path = Path(root) / f'{safe_account}.json'

    def load(self) -> RealmRaidCheckpoint | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            checkpoint = RealmRaidCheckpoint.from_dict(data)
            if checkpoint.schema_version != 1:
                return None
            return checkpoint
        except (OSError, ValueError, TypeError):
            return None

    def save(self, checkpoint: RealmRaidCheckpoint) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.touch()
        payload = json.dumps(asdict(checkpoint), ensure_ascii=False, indent=2)
        temporary = self.path.with_suffix(self.path.suffix + '.tmp')
        temporary.write_text(payload + '\n', encoding='utf-8')
        os.replace(temporary, self.path)

    def clear(self) -> None:
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
        board_signature=snapshot.board_signature,
        mode=mode.value,
        target_level=target_level,
        observed_level=snapshot.challenge_level,
        failure_count=0,
        success_count=snapshot.success_count,
        recovery_hold=recovery_hold,
    )
    checkpoint.touch(snapshot.captured_at)
    return checkpoint


def reconcile_checkpoint(
    account: str,
    snapshot: BoardSnapshot,
    target_level: int,
    checkpoint: RealmRaidCheckpoint | None,
) -> RealmRaidCheckpoint:
    if checkpoint_matches(checkpoint, snapshot, target_level):
        checkpoint.success_count = snapshot.success_count
        checkpoint.board_signature = snapshot.board_signature
        checkpoint.observed_level = snapshot.challenge_level
        checkpoint.touch(snapshot.captured_at)
        return checkpoint

    partial_board = bool(snapshot.broken or snapshot.failure_marked or snapshot.success_count)
    if partial_board:
        return create_checkpoint(
            account=account,
            snapshot=snapshot,
            target_level=target_level,
            mode=LevelMode.RECOVERY_HOLD,
            recovery_hold=True,
        )

    return create_checkpoint(
        account=account,
        snapshot=snapshot,
        target_level=target_level,
        mode=choose_level_mode(snapshot.challenge_level, target_level),
    )


def decide_next_action(
    snapshot: BoardSnapshot,
    checkpoint: RealmRaidCheckpoint,
    min_valid_levels: int = 6,
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
