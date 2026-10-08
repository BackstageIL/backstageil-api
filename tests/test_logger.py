"""JSON logging setup."""

import json
import logging

from app.core.logger import JsonFormatter, configure_logging


def test_http_client_request_lines_are_never_logged() -> None:
    # They carry full URLs, and the website deploy hook URL is a secret
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        configure_logging("DEBUG")

        assert not logging.getLogger("httpx2").isEnabledFor(logging.INFO)
        assert not logging.getLogger("httpcore").isEnabledFor(logging.INFO)
        assert logging.getLogger("httpx2").isEnabledFor(logging.WARNING)
        assert logging.getLogger("app.services").isEnabledFor(logging.DEBUG)
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_json_format() -> None:
    record = logging.LogRecord("app.x", logging.ERROR, __file__, 1, "Failed %s", ("once",), None)

    payload = json.loads(JsonFormatter().format(record))

    assert payload["severity"] == "ERROR"
    assert payload["logger"] == "app.x"
    assert payload["message"] == "Failed once"
    assert payload["time"].endswith("+00:00")
