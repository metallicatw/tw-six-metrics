"""Settings, loaded from TOML.

Nothing that a user might reasonably want to change is written in code.  The
workbook kept its switches scattered across 〔設定〕G1:G5, 〔EPS預估與估價〕D2,
F16, H16, K2, L2 and a handful of yellow cells; they are all gathered here.
"""

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
    """〔EPS預估與估價〕's yellow cells."""

    revenue_growth_method: str = "1&6"  # D2: "1&6" | "3&6" | "12m"
    margin_method: str = "4q_avg"  # F16: 4q_avg | 4q_min | current
    pe_basis: str = "avg_5y"  # K2
    pe_source: str = "computed"  # L2: computed | public
    payout_basis: str = "avg_5y"
    river_low_percentile: float = 0.025   # 〔河流圖〕J1
    river_high_percentile: float = 0.975  # 〔河流圖〕L1


@dataclass
class IngestSettings:
    cache_dir: str = ".cache/http"
    cache_ttl_hours: float = 6.0
    min_interval_seconds: float = 1.2
    retries: int = 4
    #: MoneyDJ mirrors.  Never enable this in CI — see ingest/moneydj.py.
    enable_moneydj_fallback: bool = False
    moneydj_host: str = "https://moneydj.emega.com.tw"


@dataclass
class ReportSettings:
    site_dir: str = "site"
    title: str = "台股與全球市場觀測站"
    subtitle: str = "由公開資料自動產生"
    #: ``owner/name`` of the GitHub repository this site is published from.
    #:
    #: The published site cannot fetch a stock itself — the browser refuses the
    #: cross-origin request and the engine is Python — but it *can* ask this
    #: repository to do it, by opening a pre-filled issue that a workflow picks
    #: up.  Empty turns that offer off, which is what a fork with no Actions
    #: budget, or a site published anywhere else, should get.
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
            data_dir=settings.get("data_dir", "data"),
            periods=int(settings.get("periods", 9)),
        )


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _build(cls: type, data: dict[str, Any]):  # type: ignore[no-untyped-def]
    known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
    return cls(**{k: v for k, v in data.items() if k in known})
