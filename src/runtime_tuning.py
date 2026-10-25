"""
Process-level memory tuning for the glibc allocator (Linux).

With glibc's defaults the large temporary buffers of a search live in per-thread arenas that are never returned to the
system, so the resident memory of a server grows with every worker thread that touched them (measured with the vector
database used before: 180 MB -> 884 MB after 12 searches, 185 MB with the settings below). Large blocks go to mmap
(returned on free) and the number of arenas is capped. Environment variables MALLOC_MMAP_THRESHOLD_ and MALLOC_ARENA_MAX
do the same when set before the process starts (legal-rag.service and the Dockerfile set them).
"""
import ctypes
import logging
import sys

logger = logging.getLogger(__name__)

M_MMAP_THRESHOLD = -3
M_ARENA_MAX = -8


def tune_malloc(mmap_threshold: int = 65536, arena_max: int = 2) -> bool:
    """Applies the settings to the running process; returns False where glibc's mallopt is not available."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        libc = ctypes.CDLL("libc.so.6")
        ok_mmap = libc.mallopt(M_MMAP_THRESHOLD, mmap_threshold)
        ok_arena = libc.mallopt(M_ARENA_MAX, arena_max)
        return bool(ok_mmap and ok_arena)
    except Exception as e:      # musl, non-glibc: the memory simply is not tuned
        logger.info(f"malloc tuning not applied: {e}")
        return False
