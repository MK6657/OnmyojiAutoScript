# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import asyncio
import json
import time
from pathlib import Path
from typing import Annotated, Any
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError
from datetime import datetime, timedelta
from module.config.utils import convert_to_underscore
from module.config.config_model import ConfigModel
from module.config.config_transaction import (
    ConfigRevisionConflict,
    apply_json_patch,
    file_revision,
    merge_validated_existing,
)

from module.logger import logger
from module.server.main_manager import mm
from module.server.script_process import (
    AccountRunLease,
    AccountLeaseError,
    ProcessStopError,
    ScriptState,
)

from tasks.Component.config_base import TimeDelta
from tasks.XiuxingHexun.availability import xiuxing_hexun_globally_enabled


script_app = APIRouter()


class ConfigBatchField(BaseModel):
    group: str
    name: str
    value: Any
    type: str


class ConfigBatchPatch(BaseModel):
    expected_revision: str | None = None
    fields: list[ConfigBatchField] = Field(default_factory=list)


def _parse_config_value(types: str, value: Any) -> Any:
    try:
        match types:
            case 'integer':
                return int(value)
            case 'number':
                return float(value)
            case 'boolean':
                if isinstance(value, str):
                    lowered = value.lower()
                    if lowered in ('true', '1'):
                        return True
                    if lowered in ('false', '0'):
                        return False
                return bool(value)
            case 'date_time':
                return datetime.strptime(str(value), '%Y-%m-%d %H:%M:%S')
            case 'time_delta':
                text = str(value)
                date_time = datetime.strptime(text[3:], '%H:%M:%S')
                return TimeDelta(
                    days=int(text[:2]),
                    hours=date_time.hour,
                    minutes=date_time.minute,
                    seconds=date_time.second,
                )
            case 'time':
                return datetime.strptime(str(value), '%H:%M:%S').time()
            case _:
                return value
    except Exception as error:
        raise HTTPException(status_code=400, detail=f'Argument type error: {error}') from error


def _missing_task_parent_updates(
    raw_config: dict[str, Any],
    model: ConfigModel,
    task_path: str,
) -> list[tuple[tuple[str, ...], Any]]:
    """Build explicit idempotent updates for a task absent from old configs.

    Pydantic supplies defaults while loading, but that does not persist the
    missing parent back to disk.  PATCH therefore needs to add the task and
    its immediate groups in the same revision-checked transaction.
    """
    task_object = getattr(model, task_path, None)
    if task_object is None:
        return []
    defaults = task_object.model_dump()
    current_task = raw_config.get(task_path)
    if not isinstance(current_task, dict):
        return [((task_path,), defaults)]
    return [
        ((task_path, field_name), field_default)
        for field_name, field_default in defaults.items()
        if field_name not in current_task
        or (
            isinstance(field_default, dict)
            and not isinstance(current_task[field_name], dict)
        )
    ]


def _validate_config_preserving_unknown(data: dict[str, Any]) -> dict[str, Any]:
    """Validate known fields without rebuilding and truncating the JSON tree."""
    validated = ConfigModel(**data).model_dump()
    return merge_validated_existing(data, validated)


def _task_update_path(
    model: ConfigModel,
    task_path: str,
    group: str,
    argument: str,
) -> tuple[str, ...]:
    task_object = getattr(model, task_path, None)
    if task_object is None:
        raise HTTPException(status_code=404, detail=f'Config task not found: {task_path}')
    group_path = convert_to_underscore(group)
    field_path = convert_to_underscore(argument)
    group_object = getattr(task_object, group_path, None)
    is_scalar_group = (
        group_path == field_path
        and hasattr(task_object, field_path)
        and not isinstance(group_object, BaseModel)
    )
    if is_scalar_group:
        return task_path, field_path
    if group_object is None or not hasattr(group_object, field_path):
        raise HTTPException(
            status_code=404,
            detail=f'Config field not found: {task_path}.{group_path}.{field_path}',
        )
    return task_path, group_path, field_path


def _guard_activity_availability(
    task_path: str,
    update_path: tuple[str, ...],
    value: Any,
) -> None:
    if (
        task_path == 'xiuxing_hexun'
        and update_path[-2:] == ('scheduler', 'enable')
        and bool(value)
        and not xiuxing_hexun_globally_enabled()
    ):
        raise HTTPException(status_code=409, detail='XiuxingHexun activity is globally disabled')


# DeepSeek-14 B1/A1 v2: atomic claim ledger. Key = command_id; each entry
# carries a fingerprint (script_name + command) and a state machine
# in_progress -> completed|failed. Both the WS endpoint and the REST fallback
# claim BEFORE executing, so a concurrent same-id request can never double-run:
# same fingerprint -> in_progress wait/replay, different fingerprint -> 409.
_COMMAND_LEDGER: dict[str, dict] = {}
_COMMAND_LEDGER_TTL_SECONDS = 300.0


def _command_fingerprint(command: str, script_name: str | None) -> tuple:
    return (str(script_name or ""), str(command))


def _ledger_reap() -> None:
    # DeepSeek-14 B1 v3: only terminal entries are TTL-reaped. An active
    # in_progress command must never be reclaimable, no matter how long it
    # runs.
    now = time.monotonic()
    stale = [
        key for key, entry in _COMMAND_LEDGER.items()
        if entry["state"] in {"completed", "failed"}
        and now - entry["stamp"] > _COMMAND_LEDGER_TTL_SECONDS
    ]
    for key in stale:
        _COMMAND_LEDGER.pop(key, None)


def _ledger_claim(command_id: str, command: str, script_name: str | None) -> dict:
    """Atomic claim. Returns {'ok': True, 'entry': ...} for a fresh claim,
    {'ok': False, 'status': state, 'result': ...} for the same fingerprint,
    or {'ok': False, 'status': 'conflict'} when the fingerprint differs."""
    _ledger_reap()
    entry = _COMMAND_LEDGER.get(command_id)
    fingerprint = _command_fingerprint(command, script_name)
    if entry is None:
        entry = {
            "fingerprint": fingerprint,
            "state": "in_progress",
            "result": None,
            "stamp": time.monotonic(),
        }
        _COMMAND_LEDGER[command_id] = entry
        return {"ok": True, "entry": entry}
    if entry["fingerprint"] != fingerprint:
        return {"ok": False, "status": "conflict"}
    return {"ok": False, "status": entry["state"], "result": entry["result"]}


def _ledger_complete(command_id: str, result: dict, *, failed: bool = False) -> None:
    entry = _COMMAND_LEDGER.get(command_id)
    if entry is None:
        return
    entry["state"] = "failed" if failed else "completed"
    entry["result"] = result
    # refresh the stamp so the TTL counts from completion, not from claim
    entry["stamp"] = time.monotonic()


async def handle_script_command(script_process, websocket, request: dict, *, script_name: str | None = None) -> bool:
    command_id = str(request.get("command_id") or "").strip()
    command = str(request.get("command") or "").strip()
    if not command_id:
        return False
    if command not in {"start", "stop", "get_state", "get_schedule"}:
        await websocket.send_json({
            "type": "command_result",
            "command_id": command_id,
            "command": command,
            "status": "failed",
            "success": False,
            "reason": "unsupported_command",
        })
        return True

    if command in {"start", "stop"}:
        # DeepSeek-14 B1 v2: claim BEFORE ack/execute so a concurrent same-id
        # WS/REST request can never double-run.
        claim = _ledger_claim(command_id, command, script_name)
        if not claim["ok"]:
            if claim["status"] == "conflict":
                await websocket.send_json({
                    "type": "command_result",
                    "command_id": command_id,
                    "command": command,
                    "status": "failed",
                    "success": False,
                    "reason": "command_id_conflict",
                })
                return True
            if claim["status"] == "in_progress":
                await websocket.send_json({
                    "type": "command_result",
                    "command_id": command_id,
                    "command": command,
                    "status": "in_progress",
                    "success": False,
                    "reason": "duplicate_command_in_progress",
                })
                return True
            # completed / failed -> replay the stored outcome verbatim
            await websocket.send_json(claim["result"])
            return True

    await websocket.send_json({
        "type": "command_ack",
        "command_id": command_id,
        "command": command,
        "status": "accepted",
    })
    try:
        changed = False
        if command == "start":
            changed = await script_process.start(source=f"ws:{command_id}")
        elif command == "stop":
            changed = await script_process.stop(source=f"ws:{command_id}")
        elif command == "get_state":
            await websocket.send_json({"state": script_process.state})
        elif command == "get_schedule":
            if not script_name:
                raise RuntimeError("script_name_required")
            config = mm.config_cache(script_name)
            config.get_next()
            await websocket.send_json({"schedule": config.get_schedule_data()})
        result_payload = {
            "type": "command_result",
            "command_id": command_id,
            "command": command,
            "status": "completed",
            "success": True,
            "changed": bool(changed),
            "state": int(script_process.state),
            "run_id": getattr(script_process, "_run_id", None),
        }
        if command in {"start", "stop"}:
            _ledger_complete(command_id, result_payload)
        await websocket.send_json(result_payload)
    except Exception as error:
        logger.exception(
            f'[{script_name or "unknown"}] command failed: id={command_id}, command={command}'
        )
        result_payload = {
            "type": "command_result",
            "command_id": command_id,
            "command": command,
            "status": "failed",
            "success": False,
            "reason": f"{type(error).__name__}: {error}",
        }
        if command in {"start", "stop"}:
            _ledger_complete(command_id, result_payload, failed=True)
        await websocket.send_json(result_payload)
    return True


def _ownership_conflict(error: Exception) -> HTTPException:
    return HTTPException(status_code=409, detail=str(error))


async def _stop_for_account_mutation(script_process, source: str) -> None:
    if script_process is None:
        return
    if (
        script_process.state != ScriptState.INACTIVE
        or bool(getattr(script_process, 'retains_ownership', False))
    ):
        try:
            await script_process.stop(source=source)
        except (ProcessStopError, AccountLeaseError) as error:
            raise _ownership_conflict(error) from error


@script_app.get('/test')
async def script_test():
    return 'success'

@script_app.get('/script_menu')
async def script_menu():
    return mm.config_cache('template').gui_menu_list
# ----------------------------------   配置文件管理   ----------------------------------
@script_app.get('/config_list')
async def config_list():
    return mm.all_script_files()

@script_app.post('/config_copy')
async def config_copy(file: str, template: str = 'template'):
    mm.copy(file, template)
    return mm.all_script_files()

@script_app.get('/config_new_name')
async def config_new_name():
    return mm.generate_script_name()

@script_app.get('/config_all')
async def config_all():
    return mm.all_json_file()


@script_app.put('/config')
async def config_rename(old_name: str = '', new_name: str = ''):
    """
    update config name
    :param old_name: old config name
    :param new_name: new config name
    :return: True or False
    """
    if old_name == new_name or new_name == '':
        return False
    script_process = mm.get_script_process(old_name)
    await _stop_for_account_mutation(script_process, 'rename')
    mutation_lease = AccountRunLease(old_name)
    if not mutation_lease.acquire():
        raise HTTPException(status_code=409, detail=f'Account is owned by another Core: {old_name}')
    try:
        if not mm.rename(old_name, new_name):
            raise HTTPException(status_code=400, detail='Rename failed')
        mm.remove_script_process(old_name)
        return True
    finally:
        mutation_lease.release()


@script_app.delete('/config')
async def config_delete(name: str = ''):
    """
    delete config file
    :param name: config name
    :return: True or False
    """
    if name == '' or name == 'template':
        raise HTTPException(status_code=400, detail='Delete failed')
    script_process = mm.get_script_process(name)
    await _stop_for_account_mutation(script_process, 'delete')
    mutation_lease = AccountRunLease(name)
    if not mutation_lease.acquire():
        raise HTTPException(status_code=409, detail=f'Account is owned by another Core: {name}')
    try:
        if not mm.delete(name):
            raise HTTPException(status_code=400, detail='Delete failed')
        mm.remove_script_process(name)
        return True
    finally:
        mutation_lease.release()


@script_app.put('/config/task/copy')
async def task_copy(task_name: str, dest_config_name: str, source_config_name: str):
    if not mm.has_script_process(dest_config_name) or not mm.has_script_process(source_config_name):
        return False
    source_task = getattr(mm.config_cache(source_config_name).model, convert_to_underscore(task_name), None)
    if source_task is None:
        return False
    return mm.config_cache(dest_config_name).model.copy_script_task(task_name, source_task)


@script_app.put('/config/task/group/copy')
async def task_group_copy(task_name: str, group_name: str, dest_config_name: str, source_config_name: str):
    if not mm.has_script_process(dest_config_name) or not mm.has_script_process(source_config_name):
        return False
    source_task = getattr(mm.config_cache(source_config_name).model, convert_to_underscore(task_name), None)
    if source_task is None:
        return False
    return mm.config_cache(dest_config_name).model.copy_task_group(task_name, group_name, source_task)


# ---------------------------------   脚本实例管理   ----------------------------------
@script_app.get('/{script_name}/start')
async def script_start(script_name: str, command_id: str | None = None):
    # DeepSeek-14 B1/A1 v2: atomic claim — concurrent same-id WS/REST can never
    # double-run; different fingerprint is a 409; in_progress returns 202-shape.
    if command_id:
        claim = _ledger_claim(command_id, "start", script_name)
        if not claim["ok"]:
            if claim["status"] == "conflict":
                raise HTTPException(status_code=409, detail='command_id conflict')
            if claim["status"] == "in_progress":
                return {"status": "in_progress", "command_id": command_id}
            logger.info(
                f'Command ledger replay: id={command_id} endpoint=start '
                f'state={claim["status"]}'
            )
            return claim["result"]
    script_process = mm.get_script_process(script_name, create=True)
    try:
        changed = await script_process.start(source=f'rest:{command_id or "anonymous"}')
    except (AccountLeaseError, ProcessStopError) as error:
        if command_id:
            _ledger_complete(
                command_id,
                {"status": "failed", "success": False, "reason": str(error)},
                failed=True,
            )
        raise _ownership_conflict(error) from error
    except Exception as error:
        # DeepSeek-14 B1 v3: an unexpected failure must not leave the ledger
        # stuck in_progress forever.
        if command_id:
            _ledger_complete(
                command_id,
                {"status": "failed", "success": False,
                 "reason": f"{type(error).__name__}: {error}"},
                failed=True,
            )
        raise
    payload = {
        "status": "completed",
        "success": True,
        "changed": changed,
        "state": int(script_process.state),
        "run_id": script_process._run_id,
    }
    if command_id:
        _ledger_complete(command_id, payload)
    return payload

@script_app.get('/{script_name}/stop')
async def script_stop(script_name: str, command_id: str | None = None):
    # DeepSeek-14 B1/A1 v2: same atomic claim semantics as start.
    if command_id:
        claim = _ledger_claim(command_id, "stop", script_name)
        if not claim["ok"]:
            if claim["status"] == "conflict":
                raise HTTPException(status_code=409, detail='command_id conflict')
            if claim["status"] == "in_progress":
                return {"status": "in_progress", "command_id": command_id}
            logger.info(
                f'Command ledger replay: id={command_id} endpoint=stop '
                f'state={claim["status"]}'
            )
            return claim["result"]
    script_process = mm.get_script_process(script_name)
    if script_process is None:
        logger.warning(f'[{script_name}] script process does not exist')
        payload = {
            "status": "completed",
            "success": True,
            "changed": False,
            "state": int(ScriptState.INACTIVE),
            "run_id": None,
        }
        if command_id:
            _ledger_complete(command_id, payload)
        return payload
    try:
        changed = await script_process.stop(source=f'rest:{command_id or "anonymous"}')
    except ProcessStopError as error:
        if command_id:
            _ledger_complete(
                command_id,
                {"status": "failed", "success": False, "reason": str(error)},
                failed=True,
            )
        raise _ownership_conflict(error) from error
    except Exception as error:
        # DeepSeek-14 B1 v3: unexpected failure must finalize the ledger.
        if command_id:
            _ledger_complete(
                command_id,
                {"status": "failed", "success": False,
                 "reason": f"{type(error).__name__}: {error}"},
                failed=True,
            )
        raise
    payload = {
        "status": "completed",
        "success": True,
        "changed": changed,
        "state": int(script_process.state),
        "run_id": script_process._run_id,
    }
    if command_id:
        _ledger_complete(command_id, payload)
    return payload

@script_app.get('/{script_name}/{task}/args')
async def script_task(script_name: str, task: str):
    return mm.config_cache(script_name).model.script_task(task)


@script_app.get('/{script_name}/config/revision')
async def script_config_revision(script_name: str):
    path = Path.cwd() / 'config' / f'{script_name}.json'
    if not path.exists():
        raise HTTPException(status_code=404, detail='Config not found')
    return {"revision": file_revision(path)}


@script_app.patch('/{script_name}/{task}/values')
async def script_set_values(
    script_name: str,
    task: str,
    payload: ConfigBatchPatch,
    if_match: Annotated[str | None, Header(alias='If-Match')] = None,
):
    path = Path.cwd() / 'config' / f'{script_name}.json'
    if not path.exists():
        raise HTTPException(status_code=404, detail='Config not found')
    expected_revision = payload.expected_revision or (if_match or '').strip().strip('"')
    if not expected_revision:
        raise HTTPException(status_code=428, detail='Config revision is required')
    task_path = convert_to_underscore(task)
    model = ConfigModel(config_name=script_name)
    try:
        raw_config = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=500, detail=f'Config could not be read: {error}') from error
    if not isinstance(raw_config, dict):
        raise HTTPException(status_code=500, detail='Config root must be an object')

    migration_updates = _missing_task_parent_updates(raw_config, model, task_path)
    updates = list(migration_updates)
    for field in payload.fields:
        update_path = _task_update_path(model, task_path, field.group, field.name)
        parsed_value = _parse_config_value(field.type, field.value)
        _guard_activity_availability(task_path, update_path, parsed_value)
        updates.append((update_path, parsed_value))

    try:
        result = apply_json_patch(
            path,
            updates,
            expected_revision=expected_revision,
            validator=_validate_config_preserving_unknown,
            allow_new_leaf=True,
        )
    except ConfigRevisionConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f'Config field not found: {error}') from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    # DeepSeek-13 1.6 (F-4): any scheduler.* write through this bulk route must
    # leave a SCHEDULE_DECISION audit record (the route itself is an audit
    # blind spot for cross-task schedule changes).
    for update_path_, _ in updates:
        if 'scheduler' in update_path_:
            logger.info(
                'SCHEDULE_DECISION task=%s path=%s caller=PATCH /values (audit)',
                task_path, '.'.join(map(str, update_path_)),
            )
    return {
        "saved": True,
        "updated": len(updates),
        "migrated": len(migration_updates),
        "revision": result.revision,
    }

@script_app.put('/{script_name}/{task}/{group}/{argument}/value')
async def script_set_value(
    script_name: str,
    task: str,
    group: str,
    argument: str,
    types: str,
    value,
    if_match: Annotated[str | None, Header(alias='If-Match')] = None,
):  # C4: 原名 script_task 遮蔽上面的同名函数
    path = Path.cwd() / 'config' / f'{script_name}.json'
    if not path.exists():
        raise HTTPException(status_code=404, detail='Config not found')
    task_path = convert_to_underscore(task)
    model = ConfigModel(config_name=script_name)
    try:
        raw_config = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=500, detail=f'Config could not be read: {error}') from error
    if not isinstance(raw_config, dict):
        raise HTTPException(status_code=500, detail='Config root must be an object')

    parsed_value = _parse_config_value(types, value)
    # DeepSeek-14 B5: every task (xiuxing and legacy) goes through the SAME
    # atomic apply_json_patch transaction gated by the CLIENT If-Match
    # revision — check and write happen in one transaction, no TOCTOU window.
    expected_revision = (if_match or '').strip().strip('"')
    if not expected_revision:
        raise HTTPException(
            status_code=428,
            detail='If-Match header with config revision is required',
        )

    update_path = _task_update_path(model, task_path, group, argument)
    _guard_activity_availability(task_path, update_path, parsed_value)
    updates = _missing_task_parent_updates(raw_config, model, task_path)
    updates.append((update_path, parsed_value))
    try:
        result = apply_json_patch(
            path,
            updates,
            expected_revision=expected_revision,
            validator=_validate_config_preserving_unknown,
            allow_new_leaf=True,
        )
    except ConfigRevisionConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f'Config field not found: {error}') from error
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if 'scheduler' in update_path:
        logger.info(
            'SCHEDULE_DECISION task=%s path=%s caller=PUT /value (audit)',
            task_path, '.'.join(map(str, update_path)),
        )
    return True


@script_app.put('/{script_name}/{task}/sync_next_run')
async def sync_next_run(script_name: str, task: str, target_dt: str, force: bool = False):
    script_process = mm.get_script_process(script_name)
    if script_process is None:
        return False
    config = mm.config_cache(script_name)
    target = datetime.strptime(target_dt, '%Y-%m-%d %H:%M:%S') if target_dt else None
    # DeepSeek-13 1.4 (N-4): a pending failure-interval delay must not be silently
    # overwritten. Clamp the requested target unless the caller forces it.
    if target is not None and not force:
        sidecar = Path.cwd() / 'work' / f'{script_name}_failure_state.json'
        try:
            if sidecar.exists():
                state = json.loads(sidecar.read_text(encoding='utf-8'))
                entry = state.get(task) or state.get(convert_to_underscore(task))
                failed_at = None
                if isinstance(entry, dict) and entry.get('count', 0) > 0:
                    raw = entry.get('last_failed_at')
                    failed_at = datetime.fromisoformat(raw) if raw else None
                if failed_at:
                    task_object = getattr(
                        config.model, convert_to_underscore(task), None
                    )
                    scheduler = getattr(task_object, 'scheduler', None)
                    interval = getattr(scheduler, 'failure_interval', None)
                    if isinstance(interval, str):
                        interval = timedelta(interval)
                    if isinstance(interval, timedelta):
                        earliest = (failed_at + interval).replace(microsecond=0)
                        if target < earliest:
                            logger.warning(
                                f'sync_next_run clamped: task {task} failed at {failed_at}, '
                                f'earliest retry {earliest}, requested {target}'
                            )
                            target = earliest
        except Exception as error:
            logger.warning(f'sync_next_run failure-delay guard skipped: {error}')
    config.task_delay(
        task=task,
        success=True,
        target=target,
        reason='control center requested next_run synchronization',
        caller='ControlCenter.sync_next_run',
    )
    config.get_next()
    await script_process.broadcast_state({"schedule": config.get_schedule_data()})
    return True


# --------------------------------------  SSE  --------------------------------------
@script_app.get('/{script_name}/state')
async def script_task_state(script_name: str):
    async def state_generate_events():
        while True:
            # 生成 SSE 事件数据
            event_data = "data: Hello, SSE!\n\n"
            yield event_data

            # 模拟异步操作，可以替换为您的实际处理逻辑
            await asyncio.sleep(1)

    response = StreamingResponse(state_generate_events(), media_type="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    return response

@script_app.get('/{script_name}/log')
async def script_task_log(script_name: str):
    async def log_generate_events():
        while True:
            # 生成 SSE 事件数据
            event_data = "data: log\n"
            yield event_data

            # 模拟异步操作，可以替换为您的实际处理逻辑
            await asyncio.sleep(1)

    response = StreamingResponse(log_generate_events(), media_type="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    return response

# -------------------------------------- websocket --------------------------------------

@script_app.websocket("/ws/{script_name}")
async def websocket_endpoint(websocket: WebSocket, script_name: str):
    script_process = mm.get_script_process(script_name, create=True)
    await script_process.connect(websocket)

    try:
        await script_process.send_json(websocket, {"state": script_process.state})
        config = mm.config_cache(script_name)
        config.get_next()
        await script_process.send_json(websocket, {"schedule": config.get_schedule_data()})

        while True:
            # 初次进入，广播state schedule
            data = await websocket.receive_text()
            try:
                request = json.loads(data)
            except (TypeError, json.JSONDecodeError):
                request = None
            if isinstance(request, dict) and await handle_script_command(
                script_process,
                websocket,
                request,
                script_name=script_name,
            ):
                continue
            if data == 'get_state':
                await script_process.broadcast_state({"state": script_process.state})
            elif data == 'get_schedule':
                config = mm.config_cache(script_name)
                config.get_next()
                await script_process.broadcast_state({"schedule": config.get_schedule_data()})
            elif data == 'start':
                await script_process.start(source='ws')
            elif data == 'stop':
                await script_process.stop(source='ws')

    except WebSocketDisconnect:
        logger.warning(f'[{script_name}] websocket disconnect')
        await script_process.disconnect(websocket)
    except Exception as e:
        logger.exception(f'[{script_name}] websocket error: {e}')
        await script_process.disconnect(websocket)
