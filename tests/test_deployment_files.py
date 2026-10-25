"""docker-compose.yml: settings come from .env; only the container layout is set in the file itself."""
import re
from pathlib import Path

COMPOSE = (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text(encoding="utf-8")
CONTAINER_LAYOUT = {"STORAGE_DIR", "CACHE_DB_PATH", "HOST"}


def test_compose_reads_every_setting_from_env_file():
    assert re.search(r"^\s*env_file:\s*\n\s*-\s*\.env\s*$", COMPOSE, re.M)


def test_compose_does_not_keep_a_copy_of_the_settings():
    """A list of settings here drifted from src/config.py: the keys of the generation provider, Jev and Huquq+ never
    reached the container, which then ran with the code defaults."""
    environment = COMPOSE.split("environment:", 1)[1].split("volumes:", 1)[0]
    assert set(re.findall(r"^\s*-\s*([A-Z][A-Z0-9_]*)=", environment, re.M)) <= CONTAINER_LAYOUT


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")


def test_the_image_finds_its_packages_for_a_user_without_a_home():
    """`adduser --system` gives HOME=/nonexistent: Python then looked for the packages in /nonexistent/.local and the
    container died at start with "No module named 'uvicorn'"."""
    assert "PYTHONUSERBASE=/home/appuser/.local" in DOCKERFILE


def test_the_image_installs_the_locked_versions_and_the_runtime_has_no_test_tools():
    assert "-c requirements.lock" in DOCKERFILE and (ROOT / "requirements.lock").exists()
    runtime = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "pytest" not in runtime and "pyflakes" not in runtime
    assert "pytest" in (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")


def test_the_example_env_does_not_open_the_administration():
    """Copying .env.example next to an ADMIN_API_KEY must not turn the local-connection access on: behind a proxy that does
    not forward X-Forwarded-For every visitor would look local."""
    assert not re.search(r"^ADMIN_LOOPBACK_ENABLED\s*=\s*true", ENV_EXAMPLE, re.M | re.I)


def test_every_setting_of_the_example_env_exists():
    from src.config import Settings

    keys = re.findall(r"^([A-Z][A-Z0-9_]*)=", ENV_EXAMPLE, re.M)
    unknown = [k for k in keys if k not in Settings.model_fields]
    assert keys and not unknown, unknown


def test_the_image_leaves_the_corpus_caches_out():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    for path in ("data/raw_lex/", "data/raw/", "data/golden_dataset/", "data/sources/built_articles.json", "tests/"):
        assert path in ignored, path


def test_the_example_env_shows_the_defaults_so_copying_it_changes_nothing():
    """A value in .env.example that differs from the code default is a silent change for everyone who copies the file
    (and the file and the code drift apart): the chat model and the numbers must be the ones the code uses."""
    from src.config import Settings

    shown = dict(re.findall(r"^([A-Z][A-Z0-9_]*)=(\S+)\s*$", ENV_EXAMPLE, re.M))
    assert shown["GENERATION_MODEL_PRIMARY"] == "deepseek/deepseek-v4-flash-0731"
    for key, value in shown.items():
        default = Settings.model_fields[key].default
        assert Settings.model_validate({key: value}).model_dump()[key] == default, (key, value, default)


def test_the_example_env_stays_short():
    """Tuning knobs belong in src/config.py with a comment, not in a file everybody has to read: only what a deployment
    must set (key, model, admin password, proxies, budget, webhook secret) is listed."""
    keys = re.findall(r"^([A-Z][A-Z0-9_]*)=", ENV_EXAMPLE, re.M)
    assert len(keys) <= 10, keys


def _compose(name="docker-compose.yml") -> dict:
    import yaml

    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def test_the_service_is_reachable_from_this_host_only_and_cannot_starve_its_neighbours():
    service = _compose()["services"]["legal-rag-api"]
    assert service["ports"] and all(p.startswith("127.0.0.1:") for p in service["ports"])     # never the internet
    limits = service["deploy"]["resources"]["limits"]
    assert limits["memory"] == "800M" and "cpus" not in limits      # a hard CPU cap stalls the container in 100 ms steps
    assert service["cpu_shares"] < 1024                                # but the host's other services come first
    assert service["oom_score_adj"] > 0                     # the kernel stops this service before a neighbour's database
    assert service["cap_drop"] == ["ALL"] and "no-new-privileges:true" in service["security_opt"]
    assert service["logging"]["options"]["max-size"] and service["logging"]["options"]["max-file"]


def test_the_bot_override_joins_the_network_of_the_bot_and_opens_no_port():
    override = _compose("docker-compose.bot.yml")
    assert set(override["services"]["legal-rag-api"]["networks"]) == {"default", "bot"}
    assert override["networks"]["bot"]["external"] is True
    assert "BOT_NETWORK" in override["networks"]["bot"]["name"]
    assert "ports" not in override["services"]["legal-rag-api"]


def test_every_volume_of_the_service_exists_in_the_repository_layout():
    mounted = [v.split(":")[0] for v in _compose()["services"]["legal-rag-api"]["volumes"]]
    assert {"./data/store", "./data/cache", "./data/sources", "./data/backups"} == set(mounted)


def test_the_image_installs_wheels_only_and_the_unit_binds_to_loopback():
    assert "--only-binary=:all:" in DOCKERFILE and "build-essential" not in DOCKERFILE
    unit = (ROOT / "legal-rag.service").read_text(encoding="utf-8")
    assert "--host 127.0.0.1" in unit and "0.0.0.0" not in unit
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert "eval/" in ignored            # the evaluation caches are 150 MB the service never reads


def test_the_runtime_needs_no_vector_database():
    """The vector database this replaced crashed with "Illegal instruction" on CPUs without AVX2 (the target server's
    Xeon E5-2670): the runtime is numpy and SQLite only."""
    runtime = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "lancedb" not in runtime and "pyarrow" not in runtime
    assert "lancedb" not in (ROOT / "requirements.lock").read_text(encoding="utf-8").lower()
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import|from)\s+(lancedb|pyarrow)\b", text, re.M), path


def test_the_vector_search_uses_one_blas_thread_everywhere():
    """OpenBLAS's worker threads spin-wait: 59 ms of CPU for an 8 ms product, 16x the CPU per question."""
    import subprocess
    import sys

    unit = (ROOT / "legal-rag.service").read_text(encoding="utf-8")
    assert "OPENBLAS_NUM_THREADS=1" in DOCKERFILE and "OPENBLAS_NUM_THREADS=1" in unit
    code = "import os; os.environ.pop('OPENBLAS_NUM_THREADS', None); import src; print(os.environ['OPENBLAS_NUM_THREADS'])"
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "1"
