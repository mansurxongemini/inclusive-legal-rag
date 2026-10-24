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

    read_by_scripts = {"GATEWAY_API_KEY"}      # scripts/eval_3way_sample.py reads it straight from the environment
    keys = re.findall(r"^([A-Z][A-Z0-9_]*)=", ENV_EXAMPLE, re.M)
    unknown = [k for k in keys if k not in Settings.model_fields and k not in read_by_scripts]
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
