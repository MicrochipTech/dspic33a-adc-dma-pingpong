"""Parameter sets of the FilterDesign GUI as JSON files.

All files live in one directory (default: ./presets next to this module, override with
the environment variable FDESIGN_PRESETS or `app.py --presets DIR`). The file
default.json is loaded when the GUI starts; if it does not exist it is created from the
built-in defaults.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRESET_DIR = Path(os.environ.get("FDESIGN_PRESETS", HERE / "presets"))
DEFAULT_NAME = "default.json"
FORMAT = "fdesign-gui"
VERSION = 1


class PresetError(Exception):
    pass


def set_directory(path: str | Path) -> None:
    global PRESET_DIR
    PRESET_DIR = Path(path).expanduser().resolve()


def sanitize(name: str) -> str:
    """File name inside the preset directory: no path parts, safe characters, .json suffix."""
    base = Path(str(name).strip().replace("\\", "/")).name
    if base.lower().endswith(".json"):
        base = base[:-5]
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")
    if not base:
        raise PresetError("invalid file name")
    return base + ".json"


def path_of(name: str) -> Path:
    return PRESET_DIR / sanitize(name)


def list_presets() -> list[str]:
    """JSON files in the preset directory, default.json first."""
    if not PRESET_DIR.is_dir():
        return []
    names = sorted((p.name for p in PRESET_DIR.glob("*.json") if p.is_file()), key=str.lower)
    if DEFAULT_NAME in names:
        names.remove(DEFAULT_NAME)
        names.insert(0, DEFAULT_NAME)
    return names


def exists(name: str) -> bool:
    return path_of(name).is_file()


def check(data: object) -> dict:
    if not isinstance(data, dict):
        raise PresetError("not a parameter set (JSON object expected)")
    if data.get("format") != FORMAT:
        raise PresetError(f"not a FilterDesign parameter set (format must be '{FORMAT}')")
    return data


def read(name: str) -> dict:
    p = path_of(name)
    try:
        return check(json.loads(p.read_text(encoding="utf-8")))
    except FileNotFoundError as e:
        raise PresetError(f"{p.name} not found in {PRESET_DIR}") from e
    except json.JSONDecodeError as e:
        raise PresetError(f"{p.name}: invalid JSON ({e.msg}, line {e.lineno})") from e


def write(name: str, data: dict) -> Path:
    """Writes atomically (temporary file + rename)."""
    p = path_of(name)
    PRESET_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"format": FORMAT, "version": VERSION, **{k: v for k, v in data.items()
                                                       if k not in ("format", "version")}}
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return p
