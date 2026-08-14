# DeepSeek-14 O14-2: print() must not bypass FlutterLogStream pipe protection.
import os
import tempfile
import unittest

# Self-isolating: redirect test logs BEFORE importing module.logger so this
# module stays hermetic under any runner (unittest/pytest/plain python).
os.environ.setdefault("OAS_TEST_LOGDIR", tempfile.mkdtemp(prefix="oas-test-logs-"))

from module.logger import FlutterHandler, FlutterLogStream, logger  # noqa: E402
import module.logger as ml  # noqa: E402


class BrokenPipe:
    def __init__(self):
        self.calls = 0

    def send(self, msg):
        self.calls += 1
        raise BrokenPipeError(32, "pipe closed", None, 232, None)


class LoggerPrintPipeProtectionTest(unittest.TestCase):
    def setUp(self):
        self.saved_handlers = list(logger.handlers)
        self.saved_log_file = getattr(logger, "log_file", None)
        logger.handlers = [h for h in logger.handlers if not isinstance(h, FlutterHandler)]
        # Unique per-run log file: assertions are immune to cross-run
        # accumulation in a shared test-log directory.
        import uuid
        self.log_name = f"o14-2-{uuid.uuid4().hex[:8]}"
        logger.set_file_logger(name=self.log_name)
        self.file_handler = next(
            h for h in logger.handlers if isinstance(h, ml.RichFileHandler)
        )

    def tearDown(self):
        # DeepSeek-14 P2: close the per-test file handler so the run ends
        # without ResourceWarnings, and restore the original log_file binding.
        try:
            self.file_handler.console.file.close()
        except Exception:
            pass
        logger.handlers = self.saved_handlers
        if self.saved_log_file is not None:
            logger.log_file = self.saved_log_file

    def test_print_survives_broken_pipe_and_degrades(self):
        pipe = BrokenPipe()
        stream = FlutterLogStream(func=pipe.send)
        from rich.console import Console
        console = Console(file=stream, force_terminal=False, force_interactive=False,
                          no_color=True, highlight=False, width=80)
        handler = FlutterHandler(console=console, show_path=False, show_time=False,
                                 show_level=True, rich_tracebacks=True,
                                 tracebacks_show_locals=True, tracebacks_extra_lines=3,
                                 highlighter=None)
        logger.addHandler(handler)
        try:
            def file_content():
                self.file_handler.console.file.flush()
                with open(logger.log_file, encoding="utf-8") as fh:
                    return fh.read()

            # 1) first print hits the broken pipe: must not raise, must degrade
            ml.print("o14-2 probe one")
            self.assertEqual(pipe.calls, 1)
            self.assertIsNone(stream._func)
            # the one-time degraded notice reaches the FILE handler exactly once
            self.assertEqual(file_content().count("worker log pipe broken"), 1)
            # 2) subsequent prints are no-ops on the pipe and never raise;
            #    the notice is not repeated
            ml.print("o14-2 probe two")
            self.assertEqual(pipe.calls, 1)
            self.assertEqual(file_content().count("worker log pipe broken"), 1)
        finally:
            logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()
