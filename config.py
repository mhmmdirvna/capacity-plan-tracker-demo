"""Load YAML configuration. Everything that can change with a reorg or a new cycle lives here."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass(frozen=True)
class Config:
    root: Path
    settings: dict
    status_mapping: dict
    messages: dict
    selectors: dict
    form_mapping: dict

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.settings.get("timezone", "Asia/Jakarta"))

    @property
    def deadline(self) -> datetime:
        return datetime.fromisoformat(self.settings["deadline"]).replace(tzinfo=self.tz)

    @property
    def cycle_year(self) -> int:
        return int(self.settings["cycle_year"])

    def path(self, key: str) -> Path:
        p = Path(self.settings["paths"][key])
        return p if p.is_absolute() else self.root / p


def load_config(config_dir: Path | None = None) -> Config:
    config_dir = config_dir or ROOT / "config"
    return Config(
        root=config_dir.parent,
        settings=_load(config_dir / "settings.yaml"),
        status_mapping=_load(config_dir / "status_mapping.yaml"),
        messages=_load(config_dir / "message_templates.yaml"),
        selectors=_load(config_dir / "scraper_selectors.yaml"),
        form_mapping=_load(config_dir / "form_mapping.yaml"),
    )
