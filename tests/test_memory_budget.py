import sys


def test_no_local_model_dependencies():
    """Verify Section 0 & 12 requirement: No local model weights loaded anywhere in process."""
    forbidden = ["torch", "transformers", "onnxruntime", "sentence_transformers", "tensorflow"]
    for mod in forbidden:
        assert mod not in sys.modules, f"Forbidden local heavy library '{mod}' is loaded in process memory!"


def test_idle_ram_under_budget():
    """Verify Section 0 & 12 requirement: Idle RSS footprint must stay under 350MB."""
    import subprocess
    cmd = [
        sys.executable,
        "-c",
        "import gc, ctypes, sys; from src.api.routes.health import get_process_memory_mb; from src.api.app import get_store; store = get_store(); assert store.count() > 0; gc.collect(); mb = get_process_memory_mb(); print(mb); sys.exit(0 if mb < 350.0 else 1)"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Clean idle memory exceeded budget: {res.stdout.strip()} MB > 350 MB"
    rss_mb = float(res.stdout.strip())
    assert rss_mb < 350.0, f"Clean idle memory exceeded budget: {rss_mb:.2f} MB > 350 MB"


