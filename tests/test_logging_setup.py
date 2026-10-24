"""Application logging: uvicorn configures only its own loggers, so the root logger had no handler and sat at WARNING."""
import logging

import pytest

from src.logging_setup import configure_logging


@pytest.fixture
def fresh_root():
    """Returns a function that leaves the root logger unconfigured (pytest puts its capture handlers there again at the
    start of every test phase, so it has to be called inside the test) and restores everything afterwards."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    saved_quiet = {name: logging.getLogger(name).level for name in ("httpx", "httpcore")}

    def reset() -> logging.Logger:
        root.handlers = []
        root.setLevel(logging.WARNING)
        return root

    yield reset
    root.handlers = saved_handlers
    root.setLevel(saved_level)
    for name, level in saved_quiet.items():
        logging.getLogger(name).setLevel(level)


def test_the_configured_level_reaches_the_application_loggers(fresh_root):
    root = fresh_root()
    assert not logging.getLogger("src.retrieval.pipeline").isEnabledFor(logging.INFO)      # the state before the fix
    configure_logging("debug")
    assert root.level == logging.DEBUG and len(root.handlers) == 1
    assert logging.getLogger("src.retrieval.pipeline").isEnabledFor(logging.INFO)


def test_an_unknown_level_falls_back_to_info(fresh_root):
    root = fresh_root()
    configure_logging("loud")
    assert root.level == logging.INFO


def test_existing_logging_configuration_is_left_alone(fresh_root):
    root = fresh_root()
    existing = logging.NullHandler()
    root.addHandler(existing)
    root.setLevel(logging.ERROR)
    configure_logging("DEBUG")
    assert root.handlers == [existing] and root.level == logging.ERROR


def test_http_client_chatter_stays_at_warning(fresh_root):
    fresh_root()
    configure_logging("DEBUG")
    assert logging.getLogger("httpx").level == logging.WARNING and logging.getLogger("httpcore").level == logging.WARNING
