import sqlite3
from pathlib import Path
from typing import Union


class ClosingConnection(sqlite3.Connection):
    """
    sqlite3 connection whose `with` block commits (or rolls back) AND closes the handle.

    The stdlib context manager only finalizes the transaction, so every `with sqlite3.connect(...)`
    leaves an open file handle until garbage collection (ResourceWarning on Python 3.13).
    """

    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def connect(path: Union[str, Path], **kwargs) -> ClosingConnection:
    """Opens a SQLite connection that is closed automatically when used as a context manager."""
    return sqlite3.connect(str(path), factory=ClosingConnection, **kwargs)
