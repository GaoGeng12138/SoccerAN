"""Simplified Chinese team-name helpers."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

_SUFFIX_RE = re.compile(
    r"\b("
    r"fc|afc|cfc|cf|sc|ac|as|ss|ssc|us|ud|cd|rc|rcd|ogc|vfl|vfb|tsv|sv|"
    r"bsc|bc|calcio|club|football\s+club|soccer\s+club"
    r")\b",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")

# Common German/French diacritic fold for matching
_TRANSLATE = str.maketrans(
    {
        "ä": "a",
        "ö": "o",
        "ü": "u",
        "ß": "ss",
        "á": "a",
        "à": "a",
        "â": "a",
        "ã": "a",
        "é": "e",
        "è": "e",
        "ê": "e",
        "í": "i",
        "ì": "i",
        "î": "i",
        "ó": "o",
        "ò": "o",
        "ô": "o",
        "ú": "u",
        "ù": "u",
        "û": "u",
        "ñ": "n",
        "ç": "c",
        "Ä": "a",
        "Ö": "o",
        "Ü": "u",
    }
)


def normalize_key(name: str) -> str:
    """Fuzzy-ish key: casefold, strip club suffixes (FC/AFC/…), fold diacritics."""
    if name is None:
        return ""
    s = str(name).strip()
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_TRANSLATE)
    s = s.casefold()
    s = _SUFFIX_RE.sub(" ", s)
    s = _PUNCT_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s).strip()
    return s


def _default_map_path() -> Path:
    return Path(__file__).resolve().parent / "team_names_zh.yaml"


def _read_yaml_map(path: Path | None = None) -> dict[str, str]:
    if path is not None:
        raw = path.read_text(encoding="utf-8")
    else:
        try:
            ref = resources.files("socceran").joinpath("team_names_zh.yaml")
            raw = ref.read_text(encoding="utf-8")
        except (FileNotFoundError, TypeError, ModuleNotFoundError, AttributeError):
            raw = _default_map_path().read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError("team_names_zh.yaml must be a mapping of name -> 中文")
    out: dict[str, str] = {}
    for k, v in data.items():
        if k is None or v is None:
            continue
        out[str(k).strip()] = str(v).strip()
    return out


@lru_cache(maxsize=4)
def load_team_name_map(path: str | None = None) -> dict[str, str]:
    """Load English/alias → 简体中文 map (exact keys as stored in YAML)."""
    p = Path(path) if path else None
    return _read_yaml_map(p)


@lru_cache(maxsize=4)
def _normalized_index(path: str | None = None) -> dict[str, str]:
    """normalize_key(alias) → Chinese; first alias wins on collision."""
    raw = load_team_name_map(path)
    idx: dict[str, str] = {}
    for eng, zh in raw.items():
        key = normalize_key(eng)
        if key and key not in idx:
            idx[key] = zh
        # Also index the Chinese value so already-translated names pass through cleanly
        zh_key = normalize_key(zh)
        if zh_key and zh_key not in idx:
            idx[zh_key] = zh
    return idx


def to_zh(name: str, *, path: str | None = None) -> str:
    """Translate team name to 简体中文; return original if unknown."""
    if name is None:
        return ""
    s = str(name).strip()
    if not s:
        return s
    raw = load_team_name_map(path)
    if s in raw:
        return raw[s]
    # case-insensitive exact among raw keys
    lower = {k.casefold(): v for k, v in raw.items()}
    if s.casefold() in lower:
        return lower[s.casefold()]
    key = normalize_key(s)
    idx = _normalized_index(path)
    if key in idx:
        return idx[key]
    return s


def use_chinese_names(cfg: dict[str, Any] | None) -> bool:
    """Read output.use_chinese_names (default True)."""
    if not cfg:
        return True
    out = cfg.get("output") or {}
    return bool(out.get("use_chinese_names", True))


def enrich_zh_columns(df, *, cfg: dict[str, Any] | None = None):
    """Add home_zh / away_zh columns when enabled (keeps English columns)."""
    import pandas as pd

    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    if not use_chinese_names(cfg):
        return df
    out = df.copy()
    if "home" in out.columns:
        out["home_zh"] = out["home"].map(to_zh)
    if "away" in out.columns:
        out["away_zh"] = out["away"].map(to_zh)
    return out


def clear_name_caches() -> None:
    """Test helper: drop LRU caches after swapping map files."""
    load_team_name_map.cache_clear()
    _normalized_index.cache_clear()
