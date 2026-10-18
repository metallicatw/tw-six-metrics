
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .rating.indicators import Rules

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


@dataclass
class ForecastSettings:

    revenue_growth_method: str = "1&6"
    margin_method: str = "4q_avg"
    pe_basis: str = "avg_5y"
    pe_source: str = "computed"
    payout_basis: str = "avg_5y"
    river_low_percentile: float = 0.025
    river_high_percentile: float = 0.975


@dataclass
class IngestSettings:
    cache_dir: str = ".cache/http"
    cache_ttl_hours: float = 6.0
    min_interval_seconds: float = 1.2
    retries: int = 4
    enable_moneydj_fallback: bool = False
    moneydj_host: str = "https://moneydj.emega.com.tw"


@dataclass
class ReportSettings:
    site_dir: str = "site"
    title: str = "金股道"
    subtitle: str = "由公開資料自動產生"
    repo: str = "metallicatw/tw-six-metrics"
    max_list_rows: int = 2000
    show_value_picks_first: bool = True


@dataclass
class UniverseSettings:
    include_listed: bool = True
    include_otc: bool = True
    exclude_industries: list[str] = field(
        default_factory=lambda: ["金融保險業", "金融保險"]
    )
    watchlist: list[str] = field(default_factory=list)
    screens: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Settings:
    rules: Rules = field(default_factory=Rules)
    forecast: ForecastSettings = field(default_factory=ForecastSettings)
    ingest: IngestSettings = field(default_factory=IngestSettings)
    report: ReportSettings = field(default_factory=ReportSettings)
    universe: UniverseSettings = field(default_factory=UniverseSettings)
    data_dir: str = "data"
    periods: int = 9

    @classmethod
    def load(cls, config_dir: Path | str | None = None) -> Settings:
        d = Path(config_dir) if config_dir else CONFIG_DIR
        settings = _read(d / "settings.toml")
        rules_raw = _read(d / "rating_rules.toml")
        universe_raw = _read(d / "universe.toml")

        return cls(
            rules=Rules.from_mapping(rules_raw) if rules_raw else Rules(),
            forecast=_build(ForecastSettings, settings.get("forecast", {})),
            ingest=_build(IngestSettings, settings.get("ingest", {})),
            report=_build(ReportSettings, settings.get("report", {})),
            universe=_build(UniverseSettings, universe_raw.get("universe", {})),
            data_dir=_resolve_data_dir(settings.get("data_dir", "data")),
            periods=int(settings.get("periods", 9)),
        )


def _resolve_data_dir(raw: str) -> str:
    path = Path(raw).expanduser()
    return str(path if path.is_absolute() else (REPO_ROOT / path))


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _build(cls: type, data: dict[str, Any]):  # type: ignore[no-untyped-def]
    known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
    return cls(**{k: v for k, v in data.items() if k in known})
