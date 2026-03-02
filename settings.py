import json
import pathlib

SETTINGS_FILE = pathlib.Path(__file__).resolve().parent / "settings.json"

_defaults = {
    "update_channel_id": None,
}


def _load() -> dict:
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, "r") as f:
            return {**_defaults, **json.load(f)}
    return dict(_defaults)


def _save(data: dict):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get(key: str):
    return _load().get(key)


def set(key: str, value):
    data = _load()
    data[key] = value
    _save(data)
