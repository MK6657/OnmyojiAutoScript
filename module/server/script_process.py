# This Python file uses the following encoding: utf-8
# @author runhey
# 脚本进程
# github https://github.com/runhey
import asyncio
import sys, os
import signal
import hashlib
import multiprocessing
import tempfile
from asyncio import QueueEmpty, CancelledError, sleep
from enum import Enum
from pathlib import Path
from threading import RLock
from uuid import uuid4

import msvcrt

from module.logger import logger
from module.server.config_manager import ConfigManager
from module.server.script_websocket import ScriptWSManager


class ScriptState(int, Enum):
    INACTIVE = 0
    RUNNING = 1
    WARNING = 2
    UPDATING = 3


class AccountLeaseError(RuntimeError):
    """Another Core process owns the account execution lease."""


class ProcessStopError(RuntimeError):
    """The worker survived terminate and kill; ownership must be retained."""


class AccountRunLease:
    """Windows cross-process lease released automatically when Core exits.

    A byte-range lock is held by an open file handle. Windows releases the lock
    when the owning Core process exits, including abnormal termination.
    """

    def __init__(self, account_name: str) -> None:
        scope = f'{Path.cwd().resolve()}::{account_name}'.casefold().encode('utf-8')
        digest = hashlib.sha256(scope).hexdigest()
        # DeepSeek-13 1.7 (F-16): tests inject OAS_LEASE_DIR so their lease
        # files never contend with the production %TEMP%\oas-account-leases dir.
        lease_dir = os.environ.get('OAS_LEASE_DIR') or str(
            Path(tempfile.gettempdir()) / 'oas-account-leases')
        self.path = Path(lease_dir) / f'{digest}.lock'
        self.account_name = account_name
        self._file = None

    @property
    def acquired(self) -> bool:
        return self._file is not None

    def acquire(self) -> bool:
        if self._file is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT)
        handle = os.fdopen(descriptor, 'r+b', buffering=0)
        try:
            if self.path.stat().st_size == 0:
                handle.write(b'0')
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except (OSError, PermissionError):
            handle.close()
            return False

        handle.seek(1)
        handle.truncate()
        handle.write(f'pid={os.getpid()} account={self.account_name}\n'.encode('utf-8'))
        handle.flush()
        handle.seek(0)
        self._file = handle
        return True

    def release(self) -> None:
        handle = self._file
        if handle is None:
            return
        self._file = None
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except (OSError, ValueError):
            pass
        finally:
            handle.close()


class ScriptProcess(ScriptWSManager):

    def __init__(self, config_name: str) -> None:
        super().__init__()
        if config_name not in ConfigManager.all_script_files():
            raise FileNotFoundError(f'{config_name}.json not found')
        self.config_name = config_name  # config_name
        self.log_pipe_out = None
        self.log_pipe_in = None
        self.state_queue = None
        self.state: ScriptState = ScriptState.INACTIVE
        self._process = None
        # The monitor runs in a separate thread/event loop.  asyncio.Lock does
        # not protect lifecycle state across those loops, so use a per-account
        # cross-thread lock and never await while holding it.
        self._lifecycle_lock = RLock()
        self._run_id: str | None = None
        self._account_lease = AccountRunLease(config_name)

    @property
    def retains_ownership(self) -> bool:
        return self._account_lease.acquired or bool(self._process and self._process.is_alive())

    def _new_ipc_locked(self) -> None:
        self._close_ipc_locked()
        self.log_pipe_out, self.log_pipe_in = multiprocessing.Pipe(False)
        self.state_queue = multiprocessing.Queue()

    def _close_ipc_locked(self) -> None:
        for pipe in (self.log_pipe_out, self.log_pipe_in):
            if pipe is not None:
                try:
                    pipe.close()
                except (OSError, ValueError):
                    pass
        if self.state_queue is not None:
            try:
                self.state_queue.close()
                self.state_queue.join_thread()
            except (OSError, ValueError):
                pass
        self.log_pipe_out = None
        self.log_pipe_in = None
        self.state_queue = None

    def _reap_dead_process_locked(self) -> tuple[str | None, int | None] | None:
        """Detach a dead child once and return its run context."""
        process = self._process
        if process is None or process.is_alive():
            return None

        run_id = self._run_id
        exitcode = getattr(process, 'exitcode', None)
        self._process = None
        self._run_id = None
        self._close_ipc_locked()
        self._account_lease.release()
        logger.warning(
            f'Script process exited: account={self.config_name}, '
            f'run_id={run_id or "unknown"}, child_pid={getattr(process, "pid", None)}, '
            f'exitcode={exitcode}'
        )
        return run_id, exitcode

    def _reap_dead_process(self) -> tuple[str | None, int | None] | None:
        with self._lifecycle_lock:
            return self._reap_dead_process_locked()

    async def _sync_dead_process(self) -> bool:
        changed = False
        with self._lifecycle_lock:
            if self._reap_dead_process_locked() is None:
                return False
            if self.state != ScriptState.INACTIVE:
                self.state = ScriptState.INACTIVE
                changed = True
        if changed:
            await self.broadcast_state({"state": self.state})
        return True

    async def start(self, source: str = 'direct') -> bool:
        """Start this account once; repeated requests are deliberately idempotent."""
        state_changed = False
        with self._lifecycle_lock:
            self._reap_dead_process_locked()
            if self._process and self._process.is_alive():
                if self.state == ScriptState.WARNING:
                    raise ProcessStopError(
                        f'cannot start while previous worker is still alive: '
                        f'account={self.config_name}, pid={self._process.pid}'
                    )
                if self.state == ScriptState.INACTIVE:
                    self.state = ScriptState.RUNNING
                    state_changed = True
                logger.info(
                    f'Script start ignored: account={self.config_name}, source={source}, '
                    f'run_id={self._run_id or "unknown"}, child_pid={self._process.pid}, '
                    'reason=already_running'
                )
                started = False
            else:
                run_id = uuid4().hex[:12]
                if not self._account_lease.acquire():
                    self.state = ScriptState.WARNING
                    state_changed = True
                    logger.warning(
                        f'Script start blocked by account lease: account={self.config_name}, '
                        f'source={source}, parent_pid={os.getpid()}'
                    )
                    raise AccountLeaseError(
                        f'account lease is held by another Core: {self.config_name}'
                    )
                self._new_ipc_locked()
                process = multiprocessing.Process(
                    target=func,
                    args=(self.config_name, self.state_queue, self.log_pipe_in,),
                    name=self.config_name,
                    daemon=True,
                )
                try:
                    process.start()
                except Exception:
                    self._close_ipc_locked()
                    self._account_lease.release()
                    self.state = ScriptState.INACTIVE
                    state_changed = True
                    logger.exception(
                        f'Script start failed: account={self.config_name}, source={source}, '
                        f'run_id={run_id}'
                    )
                    raise

                # Publish only a child that has successfully started.  The
                # monitor cannot reap a not-yet-started Process object.
                self._process = process
                self._run_id = run_id
                self.state = ScriptState.RUNNING
                state_changed = True
                started = True
                logger.info(
                    f'Script started: account={self.config_name}, source={source}, '
                    f'run_id={run_id}, parent_pid={os.getpid()}, child_pid={process.pid}'
                )

        if state_changed:
            await self.broadcast_state({"state": self.state})
        return started

    async def stop(self, source: str = 'direct') -> bool:
        state_changed = False
        failure: ProcessStopError | None = None
        with self._lifecycle_lock:
            process = self._process
            if process is None:
                if self.state != ScriptState.INACTIVE:
                    self.state = ScriptState.INACTIVE
                    state_changed = True
                self._account_lease.release()
                logger.warning(
                    f'Script stop ignored: account={self.config_name}, source={source}, '
                    'reason=not_running'
                )
                stopped = False
            else:
                run_id = self._run_id
                self.state = ScriptState.INACTIVE
                state_changed = True
                if not process.is_alive():
                    self._process = None
                    self._run_id = None
                    self._close_ipc_locked()
                    self._account_lease.release()
                    logger.info(
                        f'Script stop observed exited child: account={self.config_name}, '
                        f'source={source}, run_id={run_id or "unknown"}, exitcode={process.exitcode}'
                    )
                    stopped = False
                else:
                    logger.info(
                        f'Script stopping: account={self.config_name}, source={source}, '
                        f'run_id={run_id or "unknown"}, child_pid={process.pid}'
                    )
                    process.terminate()
                    process.join(timeout=0.7)
                    if process.is_alive():
                        logger.error(
                            f'Script terminate failed: account={self.config_name}, '
                            f'run_id={run_id or "unknown"}, child_pid={process.pid}'
                        )
                        process.kill()
                        process.join(timeout=0.7)
                    if process.is_alive():
                        self.state = ScriptState.WARNING
                        failure = ProcessStopError(
                            f'process_still_alive: account={self.config_name}, pid={process.pid}'
                        )
                        stopped = False
                        logger.critical(
                            f'Script kill failed: account={self.config_name}, source={source}, '
                            f'run_id={run_id or "unknown"}, child_pid={process.pid}; '
                            'retaining process, IPC and account lease'
                        )
                    else:
                        self._process = None
                        self._run_id = None
                        self._close_ipc_locked()
                        self._account_lease.release()
                        self.state = ScriptState.INACTIVE
                        stopped = True

        if state_changed:
            await self.broadcast_state({"state": self.state})
        if failure is not None:
            raise failure
        return stopped

    async def coroutine_broadcast_state(self):
        try:
            while 1:
                await self._sync_dead_process()
                if self.state == ScriptState.INACTIVE:
                    await sleep(1)
                    continue
                if self._process is None or self.state_queue is None:
                    await sleep(1)
                    continue
                await sleep(0.1)
                try:
                    if self.state_queue.empty():
                        await sleep(1)
                        continue
                    data = self.state_queue.get_nowait()
                    if not data:
                        await sleep(0.5)
                        continue
                    if 'state' in data and data['state'] == ScriptState.WARNING:
                        self.state = ScriptState.WARNING
                    await self.broadcast_state(data)
                except QueueEmpty as e:
                    logger.warning(f'QueueEmpty: {e}')
                    await sleep(0.5)
                    continue
                except Exception as e:
                    logger.error(f'Error: {e}')
                    continue
        except CancelledError as e:
            logger.warning(f'{self.config_name} state coroutine is cancelled')
            return

    async def coroutine_broadcast_log(self):
        try:
            while 1:
                await self._sync_dead_process()
                if self.state == ScriptState.INACTIVE:
                    await sleep(1)
                    continue
                if self._process is None or self.log_pipe_out is None:
                    await sleep(1)
                    continue
                await sleep(0.05)
                try:
                    if not self.log_pipe_out.poll():
                        await sleep(0.3)
                        continue
                    log = self.log_pipe_out.recv()
                    if not log:
                        await sleep(0.5)
                        continue
                    await self.broadcast_log(log)
                except EOFError as e:
                    await sleep(0.5)
                    logger.warning(f'EOFError: {e}')
                    continue
                except Exception as e:
                    logger.error(f'Log Error: {e}')
                    continue
        except CancelledError as e:
            logger.warning(f'{self.config_name} log coroutine is cancelled')
            return


def func(config: str, state_queue: multiprocessing.Queue, log_pipe_in) -> None:
    def signal_handler(signum, frame):
        logger.info(f'Script {config} received signal {signum}, exiting gracefully')
        log_pipe_in.close()
        state_queue.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    def start_log() -> None:
        try:
            from module.logger import set_file_logger, set_func_logger
            set_file_logger(name=config)
            set_func_logger(log_pipe_in.send)
        except Exception as e:
            logger.exception(f'Start log error')
            logger.error(f'Error: {e}')
            raise
    start_log()
    import time
    try:
        # while 1:
        #     time.sleep(1)
        #     logger.info(f'Script {config} is running')
        #     state_queue.put({"state": ScriptState.RUNNING})
        from script import Script
        script = Script(config_name=config)
        script.state_queue = state_queue
        script.loop()
    except SystemExit as e:
        logger.info(f'Script {config} process exit')
        logger.error(f'Error: {e}')
        state_queue.put({"state": ScriptState.WARNING})
        time.sleep(0.1)
        exit(-1)
    except Exception as e:
        logger.exception(f'Run script {config} error')
        logger.error(f'Error: {e}')
        raise


if __name__ == '__main__':
    p = ScriptProcess('oas1')
    p.start()
    from time import sleep
    sleep(10)
    logger.info(p._process.exitcode)
