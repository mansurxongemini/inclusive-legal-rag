"""Reading the vector store's rows the way the tests need them."""
import sqlite3


def vector_rows(vector_store) -> list:
    """Every row of the vector table as a dict (the vector as stored bytes), in insertion order."""
    with vector_store._connect() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM articles_vectors ORDER BY id")]
