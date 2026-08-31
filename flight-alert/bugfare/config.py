"""設定ファイル（JSON）の読み込みと検証。

トークンやWebhook URLは設定ファイルに直書きせず、"${ENV_NAME}" と書いて
環境変数から読ませる。設定ファイルをそのままコミットしても秘密が漏れない。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

ENV_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


class ConfigError(ValueError):
    pass


def _expand(value: Any) -> Any:
    """"${FOO}" だけの文字列を環境変数の値に置き換える。"""
    if isinstance(value, str):
        m = ENV_PATTERN.match(value.strip())
        if m:
            return os.environ.get(m.group(1), "")
        return value
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


@dataclass
class ProviderConfig:
    name: str = "travelpayouts"
    token: str = ""
    api_key: str = ""
    api_secret: str = ""
    market: str = "jp"          # Travelpayouts の市場コード
    environment: str = "test"   # Amadeus の環境: test / production
    request_pause_seconds: float = 0.4
    max_requests: int = 400
    # 日付を総当たりできないプロバイダ（Amadeus など）で、
    # 各月のどの日を代表として調べるか / 何泊で往復を組むか
    sample_days: list[int] = field(default_factory=lambda: [8, 22])
    stay_nights: int = 7
    fixtures_path: str = ""      # sample プロバイダ用

    @classmethod
    def from_dict(cls, data: dict) -> "ProviderConfig":
        cfg = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise ConfigError(f"provider に不明なキー: {sorted(unknown)}")
        return cfg


@dataclass
class SearchConfig:
    origins: list[str] = field(default_factory=lambda: ["HND", "NRT"])
    trip_types: list[str] = field(default_factory=lambda: ["round", "oneway"])
    months_ahead: int = 6
    min_days_ahead: int = 2
    limit_per_query: int = 30
    direct_only: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "SearchConfig":
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise ConfigError(f"search に不明なキー: {sorted(unknown)}")
        cfg = cls(**data)
        if not cfg.origins:
            raise ConfigError("search.origins が空です")
        cfg.origins = [o.upper() for o in cfg.origins]
        bad = [t for t in cfg.trip_types if t not in ("round", "oneway")]
        if bad:
            raise ConfigError(f"search.trip_types は round / oneway のみ: {bad}")
        if cfg.months_ahead < 1:
            raise ConfigError("search.months_ahead は 1 以上")
        return cfg


@dataclass
class Target:
    """監視したい行き先のまとまり。"""

    name: str
    destinations: list[str]
    alert_price: Optional[int] = None          # 往復でこの額以下なら即通知
    oneway_alert_price: Optional[int] = None   # 片道でこの額以下なら即通知
    drop_ratio: Optional[float] = None         # 相場比のしきい値を個別に上書き
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "Target":
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise ConfigError(f"targets に不明なキー: {sorted(unknown)}")
        target = cls(**data)
        if not target.name:
            raise ConfigError("targets[].name は必須")
        if not target.destinations:
            raise ConfigError(f"targets[{target.name}].destinations が空です")
        target.destinations = [d.upper() for d in target.destinations]
        return target

    def threshold_for(self, trip_type: str) -> Optional[int]:
        return self.alert_price if trip_type == "round" else self.oneway_alert_price


@dataclass
class DetectionConfig:
    drop_ratio: float = 0.5      # 相場の何割以下なら通知するか（0.5 = 半額以下）
    min_samples: int = 8         # 相場を信用するのに必要な観測数
    lookback_days: int = 60      # 相場を計算する期間
    mad_sigma: float = 4.0       # 中央値からの外れ具合のしきい値
    min_price_jpy: int = 3000    # これ未満はデータ不良とみなして捨てる
    max_price_jpy: int = 2_000_000

    @classmethod
    def from_dict(cls, data: dict) -> "DetectionConfig":
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise ConfigError(f"detection に不明なキー: {sorted(unknown)}")
        cfg = cls(**data)
        if not 0 < cfg.drop_ratio < 1:
            raise ConfigError("detection.drop_ratio は 0 と 1 の間")
        if cfg.min_samples < 3:
            raise ConfigError("detection.min_samples は 3 以上")
        return cfg


@dataclass
class AlertingConfig:
    cooldown_hours: int = 12       # 同じ便を再通知しない時間
    max_alerts_per_run: int = 10   # 1回の実行で送る上限（通知の洪水を防ぐ）
    price_bucket_jpy: int = 1000
    adults: int = 1
    cabin_class: str = "economy"

    @classmethod
    def from_dict(cls, data: dict) -> "AlertingConfig":
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise ConfigError(f"alerting に不明なキー: {sorted(unknown)}")
        return cls(**data)


@dataclass
class Config:
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    targets: list[Target] = field(default_factory=list)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    alerting: AlertingConfig = field(default_factory=AlertingConfig)
    notifiers: list[dict] = field(default_factory=list)
    database_path: str = "data/bugfare.sqlite3"

    @property
    def active_targets(self) -> list[Target]:
        return [t for t in self.targets if t.enabled]

    def target_for(self, destination: str) -> Optional[Target]:
        for target in self.active_targets:
            if destination.upper() in target.destinations:
                return target
        return None

    @classmethod
    def from_dict(cls, raw: dict) -> "Config":
        data = _expand(raw)
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise ConfigError(f"設定のトップレベルに不明なキー: {sorted(unknown)}")
        cfg = cls(
            provider=ProviderConfig.from_dict(data.get("provider", {})),
            search=SearchConfig.from_dict(data.get("search", {})),
            targets=[Target.from_dict(t) for t in data.get("targets", [])],
            detection=DetectionConfig.from_dict(data.get("detection", {})),
            alerting=AlertingConfig.from_dict(data.get("alerting", {})),
            notifiers=data.get("notifiers", []),
            database_path=data.get("database_path", "data/bugfare.sqlite3"),
        )
        if not cfg.active_targets:
            raise ConfigError("有効な targets が1つもありません")
        return cfg

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"設定ファイルが見つかりません: {p}")
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"設定ファイルの JSON が壊れています: {exc}") from exc
        return cls.from_dict(raw)
