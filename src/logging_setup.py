"""
Application logging. uvicorn configures only its own loggers, so without this the root logger stays at WARNING and
every INFO message of src.* (relevance gate, spend guard, maintenance, sync) is dropped.
"""
import logging

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
# one INFO line per outgoing request would drown the application's own messages
_QUIET_LOGGERS = ("httpx", "httpcore")


def configure_logging(level: str = "INFO") -> None:
    """
    Gives the root logger a handler at LOG_LEVEL. Like logging.basicConfig it does nothing when logging is already
    configured (a --log-config of the server, a test runner), and an unknown level name falls back to INFO.
    """
    numeric = logging.getLevelName(str(level).strip().upper())
    logging.basicConfig(level=numeric if isinstance(numeric, int) else logging.INFO, format=_FORMAT)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
