"""Tests for `fleet_logging.formatter` — the canonical JSON log line, both
usage shapes (stdlib `logging` via `configure_logging`/`JsonFormatter`, and
the direct `log_event` function)."""

from __future__ import annotations

import io
import json
import logging

import pytest

from fleet_logging.formatter import (
    JsonFormatter,
    configure_logging,
    log_event,
    new_run_id,
)


@pytest.fixture(autouse=True)
def _clean_root_logger():
    """Every test gets a root logger with no handlers, so `configure_logging`'s
    idempotency doesn't leak state between tests."""
    root = logging.getLogger()
    saved = root.handlers[:]
    saved_level = root.level
    root.handlers = []
    yield
    root.handlers = saved
    root.setLevel(saved_level)


def _record(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="mymodule",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    for key, val in extra.items():
        setattr(record, key, val)
    return record


class TestJsonFormatter:
    def test_required_fields_present(self):
        fmt = JsonFormatter(service="my-service")
        line = json.loads(fmt.format(_record()))
        assert line["schema_version"] == 1
        assert line["level"] == "INFO"
        assert line["service"] == "my-service"
        assert line["msg"] == "hello world"
        assert "ts" in line and line["ts"].endswith("Z")

    def test_event_defaults_to_logger_name(self):
        fmt = JsonFormatter(service="svc")
        line = json.loads(fmt.format(_record()))
        assert line["event"] == "mymodule"

    def test_explicit_event_wins_over_logger_name(self):
        fmt = JsonFormatter(service="svc")
        line = json.loads(fmt.format(_record(event="batch.completed")))
        assert line["event"] == "batch.completed"

    def test_extra_fields_pass_through(self):
        fmt = JsonFormatter(service="svc")
        line = json.loads(fmt.format(_record(run_id="run-1", items_processed=42)))
        assert line["run_id"] == "run-1"
        assert line["items_processed"] == 42

    def test_redacted_keys_are_scrubbed(self):
        fmt = JsonFormatter(service="svc")
        line = json.loads(fmt.format(_record(api_key="sk-live-abc123")))
        assert line["api_key"] == "[REDACTED]"

    def test_exc_info_sets_err_type(self):
        fmt = JsonFormatter(service="svc")
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = _record()
            record.exc_info = sys.exc_info()
        line = json.loads(fmt.format(record))
        assert line["err_type"] == "ValueError"

    def test_none_valued_extra_is_dropped(self):
        fmt = JsonFormatter(service="svc")
        line = json.loads(fmt.format(_record(outcome=None)))
        assert "outcome" not in line


class TestConfigureLogging:
    def test_emits_valid_json_to_given_stream(self):
        stream = io.StringIO()
        configure_logging("my-service", stream=stream)
        logging.getLogger("mymodule").info("hi")
        line = json.loads(stream.getvalue().strip())
        assert line["service"] == "my-service"
        assert line["msg"] == "hi"

    def test_idempotent_does_not_double_handler(self):
        stream = io.StringIO()
        configure_logging("svc", stream=stream)
        configure_logging("svc", stream=stream)
        logging.getLogger("mymodule").info("once")
        lines = [ln for ln in stream.getvalue().strip().splitlines() if ln]
        assert len(lines) == 1

    def test_defaults_to_stdout(self, capsys):
        configure_logging("svc")
        logging.getLogger("mymodule").warning("careful")
        captured = capsys.readouterr()
        line = json.loads(captured.out.strip())
        assert line["level"] == "WARNING"


class TestLogEvent:
    def test_writes_one_json_line_to_stdout_by_default(self, capsys):
        log_event("info", "run.completed", service="svc", run_id="run-1", outcome="ok")
        captured = capsys.readouterr()
        line = json.loads(captured.out.strip())
        assert line["event"] == "run.completed"
        assert line["service"] == "svc"
        assert line["run_id"] == "run-1"
        assert line["outcome"] == "ok"
        assert line["schema_version"] == 1

    def test_can_target_stderr(self):
        stream = io.StringIO()
        log_event("error", "run.failed", service="svc", stream=stream)
        line = json.loads(stream.getvalue().strip())
        assert line["event"] == "run.failed"

    def test_msg_defaults_to_event(self, capsys):
        log_event("info", "batch.completed", service="svc")
        line = json.loads(capsys.readouterr().out.strip())
        assert line["msg"] == "batch.completed"

    def test_redacts_deny_listed_fields(self, capsys):
        log_event("info", "auth.attempt", service="svc", token="secret-value")
        line = json.loads(capsys.readouterr().out.strip())
        assert line["token"] == "[REDACTED]"


class TestNewRunId:
    def test_reuses_env_run_id(self, monkeypatch):
        monkeypatch.setenv("RUN_ID", "run-from-parent")
        assert new_run_id() == "run-from-parent"

    def test_mints_a_fresh_id_when_unset(self, monkeypatch):
        monkeypatch.delenv("RUN_ID", raising=False)
        run_id = new_run_id(prefix="job")
        assert run_id.startswith("job-")

    def test_two_calls_do_not_collide(self, monkeypatch):
        monkeypatch.delenv("RUN_ID", raising=False)
        assert new_run_id() != new_run_id()
