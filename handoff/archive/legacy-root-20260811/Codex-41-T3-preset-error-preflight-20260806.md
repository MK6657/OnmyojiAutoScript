# Codex-41 T3 preset error preflight and service verification

Date: 2026-08-06
Branch: codex/mk6657-secondary-development
Scope: T3 preset/configuration error handling only. No game task was started.

## Baseline

- Core listens on `127.0.0.1:22267`.
- Bridge listens on `127.0.0.1:22367`.
- Frontend listens on `127.0.0.1:4175`.
- Bridge health returned HTTP 200 with `bridge=ok` and `core=ok`.
- Frontend returned HTTP 200.
- No account task child process was running during verification.
- The worktree already contained extensive user and earlier-agent changes. No unrelated changes were reverted.

## Root cause confirmed

1. `SwitchSoul` accepted the disabled sentinel `-1,-1` until after navigation, then raised a plain `ValueError` from the group/team range check.
2. Named preset lookup and incomplete preset names were converted to `RequestHumanTakeover` in task code.
3. `script.py` had no preset-specific boundary, so both paths reached the generic failure/exit behavior instead of allowing the scheduler to retry the task.

The result was a configuration or preset lookup problem being reported as a worker/process failure. This was separate from game combat, board recognition, and the evening-only RyouToppa test.

## Implemented

- Added `InvalidPresetConfigError` and `PresetApplyUnconfirmedError` under the existing `PresetLookupError` family.
- Added numeric preset validation before `SwitchSoul` navigation or clicks.
- Kept `-1,-1` valid when numeric soul switching is disabled; enabled numeric switching now fails before navigation.
- Converted preset name/configuration failures in GeneralBattle and RealmRaid to the preset exception family.
- Added RealmRaid preparation preflight for the numeric compatibility path.
- Added a central `script.py` preset-error boundary. It schedules the same task 60 seconds later with `server=False`, returns through the normal scheduler failure path, and does not call Restart or `exit(1)` for the first failure.
- Added offline tests for disabled/enabled `-1,-1`, malformed numeric settings, valid dispatch, named preset configuration errors, RealmRaid preparation, and scheduler retry behavior.

## Verification

All commands used the project virtual environment (`D:\OSAyys\.venv`):

- SwitchSoul preflight: 5 passed.
- GeneralBattle tests: 62 passed.
- RealmRaid tests: 77 passed.
- Server and scheduler tests: 10 passed.
- Exploration tests: 26 passed.
- Touched-file `py_compile`: passed.
- Touched-file `git diff --check`: passed.

## Not verified in this record

- No emulator clicks, preset OCR, real game battle, green-marker mapping, or RealmRaid board transition were run.
- The 60-second retry delay is intentionally a code constant for this minimal patch; making it user-configurable is a later scheduler/config task.
- Existing generic `RequestHumanTakeover` and unrelated `ValueError` paths remain unchanged.

## Next safe action

Keep automatic tasks stopped while reviewing this record. For the next real-device test, use a valid named team/soul preset or a valid numeric pair, then confirm the log chain `PREPARE_START -> TEAM_PRESET_RESULT/SOUL_PRESET_RESULT -> PREPARE_RESULT -> page_realm_raid`. Test the invalid `-1,-1` case separately only if a controlled retry is desired.
