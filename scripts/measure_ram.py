#!/usr/bin/env python3
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api.app import get_store
from src.api.routes.health import get_process_memory_mb


def audit_dependencies():
    """Verify that NO local heavy model weights or deep learning frameworks are imported."""
    forbidden = ["torch", "transformers", "onnxruntime", "sentence_transformers", "tensorflow"]
    loaded_forbidden = [mod for mod in forbidden if mod in sys.modules]
    if loaded_forbidden:
        print(f"[ERROR] Forbidden local model dependencies loaded: {loaded_forbidden}")
        return False
    print("[PASS] Zero local model dependencies loaded. Strict API-only constraint verified.")
    return True


def measure_memory():
    print("=" * 65)
    print("  UZBEKISTAN LEGAL RAG — RAM FOOTPRINT & RESOURCE AUDIT")
    print("=" * 65)

    # Trigger initialization of store and API
    store = get_store()
    count = store.count()

    rss_mb = get_process_memory_mb()
    print(f"[*] Process PID         : {os.getpid()}")
    print(f"[*] Total Articles      : {count}")
    print(f"[*] Measured Idle RSS   : {rss_mb:.2f} MB")
    print("[*] Memory Ceiling Limit: 350.00 MB")
    print(f"[*] Remaining Headroom  : {350.0 - rss_mb:.2f} MB")
    print("-" * 65)

    dep_ok = audit_dependencies()
    mem_ok = (rss_mb < 350.0)

    if mem_ok and dep_ok:
        print("\n>>> [PASSED] IDLE RAM FOOTPRINT IS WELL UNDER 350MB! <<<")
        sys.exit(0)
    else:
        print("\n>>> [FAILED] RESOURCE CEILING CRITERIA BREACHED! <<<")
        sys.exit(1)


if __name__ == "__main__":
    measure_memory()
