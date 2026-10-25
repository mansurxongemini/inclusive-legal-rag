"""
Storage: vectors in SQLite with exact numpy search (vector_store), SQLite full text and article rows (fts_store), both behind HybridStore.

Nothing is imported here on purpose: HybridStore needs the OpenRouter client, and the client's spend ledger needs
storage.sqlite_utils, so an eager import in this file made the two import each other. Import the submodule you need.
"""
