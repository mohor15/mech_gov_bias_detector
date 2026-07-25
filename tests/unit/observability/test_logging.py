from __future__ import annotations

import json
import logging

from gov_platform.observability.logging import JsonFormatter, configure_logging


def test_json_formatter_produces_valid_json() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )

    output = json.loads(formatter.format(record))

    assert output["message"] == "hello world"
    assert output["level"] == "INFO"
    assert output["logger"] == "test.logger"
    assert "timestamp" in output


def test_json_formatter_includes_extra_fields() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="failed",
        args=(),
        exc_info=None,
    )
    record.extra_fields = {"path": "/v1/ingestion/events"}  # type: ignore[attr-defined]

    output = json.loads(formatter.format(record))

    assert output["path"] == "/v1/ingestion/events"


def test_configure_logging_is_idempotent() -> None:
    configure_logging("DEBUG")
    configure_logging("DEBUG")

    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert root.level == logging.DEBUG
