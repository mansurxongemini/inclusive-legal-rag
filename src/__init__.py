"""Uzbekistan Multilingual Legal RAG Platform"""
import os

# One BLAS thread, set before numpy is imported anywhere. The vector search is one matrix-vector product (8 ms, bound by
# memory, not by arithmetic); OpenBLAS's worker threads spin-wait after each call: 59 ms of CPU for those 8 ms, so one
# question cost 1.4 s of CPU instead of 85 ms and a server with a CPU limit froze under a few parallel questions.
for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ.setdefault(_name, "1")

__version__ = "1.0.0"
