"""Local application settings. API keys stay in .env and are never returned to UI."""
import os
from pathlib import Path

_env_path = None
DEFAULTS = {
    "TRANSCRIPTION_PROVIDER": "local",
    "GROQ_MODEL": "whisper-large-v3-turbo",
    "GROQ_API_KEY": "",
}


def init(env_path):
    global _env_path
    _env_path = Path(env_path)


def load_config(include_environment=True):
    config = DEFAULTS.copy()
    if _env_path.exists():
        for line in _env_path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key in config:
                config[key] = value.strip()
    if include_environment:
        for key in DEFAULTS:
            if key in os.environ:
                config[key] = os.environ[key]
    return config


def save_config(config):
    content = "\n".join(f"{key}={config.get(key, default)}" for key, default in DEFAULTS.items())
    _env_path.parent.mkdir(parents=True, exist_ok=True)
    _env_path.write_text(content + "\n", encoding="utf-8")
    _env_path.chmod(0o600)
