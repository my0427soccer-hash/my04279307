"""どれを「バグ価格」とみなすかの判定。

3つのルールのどれかに当たれば通知する。

1. absolute  … 行き先ごとに決めた「これ以下なら理由を問わず即通知」の額
2. baseline  … 直近の相場（中央値）の何割以下か
3. outlier   … 中央値からのばらつき（MAD）で見て極端な外れ値か

1 は履歴ゼロの初日から効く。2 と 3 は履歴が min_samples 日ぶん
貯まってから効きはじめる。
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from .config import Config
from .models import Alert, Baseline, Offer
from .store import Store

log = logging.getLogger(__name__)

# 正規分布での標準偏差に MAD を合わせるための定数
MAD_SCALE = 0.6745

# MAD ルールの誤検知よけ。ばらつきが極端に小さい路線で
# わずかな値下がりを「外れ値」と言い張らないための保険。
OUTLIER_MAX_RATIO = 0.7


class Detector:
    def __init__(self, config: Config, store: Store):
        self.config = config
        self.store = store
        self._baselines: dict[str, Baseline] = {}

    def baseline_for(self, route_key: str) -> Baseline:
        if route_key not in self._baselines:
            self._baselines[route_key] = self.store.baseline(
                route_key, self.config.detection.lookback_days
            )
        return self._baselines[route_key]

    # ------------------------------------------------------------- 1件の判定

    def evaluate(self, offer: Offer) -> Optional[Alert]:
        det = self.config.detection
        if not (det.min_price_jpy <= offer.price_jpy <= det.max_price_jpy):
            log.debug("価格が想定外なので無視: %s", offer.describe())
            return None

        target = self.config.target_for(offer.destination)
        if target is None:
            return None

        baseline = self.baseline_for(offer.route_key)
        drop_ratio = target.drop_ratio if target.drop_ratio is not None else det.drop_ratio

        reasons: list[str] = []
        messages: list[str] = []

        threshold = target.threshold_for(offer.trip_type)
        if threshold is not None and offer.price_jpy <= threshold:
            reasons.append("absolute")
            messages.append(
                f"設定した通知ライン ¥{threshold:,} を下回りました"
                f"（¥{threshold - offer.price_jpy:,} 安い）"
            )

        discount: Optional[float] = None
        if baseline.samples >= det.min_samples and baseline.median:
            discount = 1.0 - offer.price_jpy / baseline.median

            if offer.price_jpy <= baseline.median * drop_ratio:
                reasons.append("baseline")
                messages.append(
                    f"直近{baseline.samples}日の相場 ¥{baseline.median:,} に対して "
                    f"{round(discount * 100)}%オフ"
                )

            if (
                baseline.mad
                and baseline.mad > 0
                and offer.price_jpy <= baseline.median * OUTLIER_MAX_RATIO
            ):
                z = MAD_SCALE * (offer.price_jpy - baseline.median) / baseline.mad
                if z <= -det.mad_sigma:
                    reasons.append("outlier")
                    messages.append(
                        f"普段の値動きの幅（±¥{int(baseline.mad):,}）から見て "
                        f"{abs(z):.1f}σ 下振れしています"
                    )

        if not reasons:
            return None

        return Alert(
            offer=offer,
            reasons=reasons,
            messages=messages,
            baseline=baseline if baseline.samples else None,
            discount=discount,
            score=self._score(offer, discount, threshold, reasons),
        )

    @staticmethod
    def _score(
        offer: Offer,
        discount: Optional[float],
        threshold: Optional[int],
        reasons: list[str],
    ) -> float:
        """通知の並び順。安さの度合いを 0〜1 強で表す。"""
        score = discount if discount is not None else 0.0
        if threshold and "absolute" in reasons:
            score = max(score, 1.0 - offer.price_jpy / threshold)
        if len(reasons) > 1:
            score += 0.1 * (len(reasons) - 1)   # 複数ルールが一致するほど確度が高い
        return round(score, 4)

    # --------------------------------------------------------- まとめての判定

    def select(self, offers: Iterable[Offer]) -> list[Alert]:
        """通知すべきものだけを、重複を除いて安い順に返す。"""
        best: dict[str, Alert] = {}
        for offer in offers:
            alert = self.evaluate(offer)
            if alert is None:
                continue
            # 同じ路線・同じ月で何本も当たったら、いちばん安いものだけ残す
            current = best.get(offer.route_key)
            if current is None or offer.price_jpy < current.offer.price_jpy:
                best[offer.route_key] = alert

        candidates = sorted(best.values(), key=lambda a: a.score, reverse=True)

        alerting = self.config.alerting
        fresh: list[Alert] = []
        for alert in candidates:
            fingerprint = alert.offer.fingerprint(alerting.price_bucket_jpy)
            if self.store.was_alerted(fingerprint, alerting.cooldown_hours):
                log.info("通知済みなので送りません: %s", alert.offer.describe())
                continue
            fresh.append(alert)
            if len(fresh) >= alerting.max_alerts_per_run:
                log.info("1回の通知上限 %d 件に達しました", alerting.max_alerts_per_run)
                break
        return fresh
