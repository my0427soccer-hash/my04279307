"""コマンドラインの入り口。"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Sequence

from . import __version__
from .config import Config, ConfigError
from .detector import Detector
from .models import Alert, Baseline, Offer
from .notifiers import build_notifiers
from .notifiers.base import plain_text
from .providers import build_provider
from .store import Store

log = logging.getLogger("bugfare")

DEFAULT_CONFIG = "config.json"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    try:
        return args.func(args)
    except ConfigError as exc:
        log.error("設定エラー: %s", exc)
        return 2
    except KeyboardInterrupt:
        log.warning("中断しました")
        return 130
    except Exception as exc:  # 予期しない失敗も終了コードで拾えるように
        log.error("失敗しました: %s", exc)
        if args.verbose:
            raise
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bugfare",
        description="羽田・成田発のバグ価格（エラーフェア）を見張って通知する",
    )
    parser.add_argument("--version", action="version", version=f"bugfare {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログを出す")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="価格を取得して、安ければ通知する（通常はこれを定期実行）")
    scan.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    scan.add_argument("--provider", help="設定のプロバイダを一時的に上書きする")
    scan.add_argument(
        "--dry-run", action="store_true", help="通知は送らず、送る内容を画面に出すだけ"
    )
    scan.add_argument(
        "--no-record", action="store_true", help="価格履歴を書き込まない（試運転用）"
    )
    scan.set_defaults(func=cmd_scan)

    demo = sub.add_parser("demo", help="APIキーなしで、検知から通知文面までの流れを試す")
    demo.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    demo.set_defaults(func=cmd_demo)

    test = sub.add_parser("test-notify", help="設定した通知先にテストの1通を送る")
    test.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    test.set_defaults(func=cmd_test_notify)

    stats = sub.add_parser("stats", help="貯まっている相場と、直近の通知を見る")
    stats.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    stats.add_argument("--route", help="路線キーで絞る（例 HND-LAX:round:2026-04）")
    stats.set_defaults(func=cmd_stats)

    prune = sub.add_parser("prune", help="古い履歴を捨てる")
    prune.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    prune.add_argument("--keep-days", type=int, default=180)
    prune.set_defaults(func=cmd_prune)

    return parser


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


# --------------------------------------------------------------------- scan


def cmd_scan(args) -> int:
    config = Config.load(args.config)
    if args.provider:
        config.provider.name = args.provider

    with Store(config.database_path) as store:
        provider = build_provider(config)
        log.info(
            "取得開始: %s / 出発地 %s / 行き先 %d か所 / %d か月先まで",
            provider.name,
            "・".join(config.search.origins),
            len(provider.destinations()),
            config.search.months_ahead,
        )

        offers = list(provider.search())
        log.info("%d 件の価格を取得しました", len(offers))
        if not offers:
            log.warning("1件も取れませんでした。トークンと路線の設定を確認してください。")
            store.log_run(0, 0, "no offers")
            return 1

        detector = Detector(config, store)
        alerts = detector.select(offers)

        if not args.no_record:
            store.record_offers(offers)

        if not alerts:
            log.info("通知に値する安値はありませんでした")
            store.log_run(len(offers), 0)
            return 0

        log.info("%d 件を通知します", len(alerts))
        if args.dry_run:
            print(plain_text(alerts, config.alerting))
            store.log_run(len(offers), 0, "dry-run")
            return 0

        sent = _dispatch(config, alerts)
        if sent:
            for alert in alerts:
                store.mark_alerted(
                    alert.offer.fingerprint(config.alerting.price_bucket_jpy),
                    alert.offer.route_key,
                    alert.offer.price_jpy,
                    alert.offer.describe(),
                )
        store.log_run(len(offers), len(alerts) if sent else 0)
        return 0 if sent else 1


def _dispatch(config: Config, alerts: list[Alert]) -> bool:
    """全通知先に送る。1つでも成功したら True。

    片方の通知先が落ちていても、残りには届いてほしいので個別に握る。
    """
    notifiers = build_notifiers(config.notifiers, config.alerting)
    if not notifiers:
        log.warning("通知先が設定されていないので、画面に出すだけにします")
        print(plain_text(alerts, config.alerting))
        return True

    sent = False
    for notifier in notifiers:
        try:
            notifier.send(alerts)
            log.info("%s に送信しました", notifier.type_name)
            sent = True
        except Exception as exc:
            log.error("%s への送信に失敗: %s", notifier.type_name, exc)
    return sent


# --------------------------------------------------------------------- demo


def cmd_demo(args) -> int:
    config = Config.load(args.config)
    config.provider.name = "sample"

    # 本番の履歴を汚さないよう、使い捨ての DB で動かす
    with tempfile.TemporaryDirectory() as tmp:
        with Store(Path(tmp) / "demo.sqlite3") as store:
            _seed_demo_history(store, config)
            provider = build_provider(config)
            offers = list(provider.search())
            alerts = Detector(config, store).select(offers)

            print(f"サンプルの価格 {len(offers)} 件のうち、{len(alerts)} 件が通知対象です。\n")
            if alerts:
                print(plain_text(alerts, config.alerting))
            else:
                print("通知対象なし。targets の alert_price を見直してください。")
    return 0


def _seed_demo_history(store: Store, config: Config) -> None:
    """相場ルールも試せるように、ここ30日ぶんの「普通の価格」を仕込む。"""
    today = date.today()
    provider = build_provider(config)
    for offer in provider.search():
        normal = (config.target_for(offer.destination).alert_price or 80_000) * 2
        for days_ago in range(1, 31):
            day = today - timedelta(days=days_ago)
            wobble = 1.0 + 0.05 * ((days_ago % 5) - 2)   # ±10%程度の日々の揺れ
            store.record_offers(
                [
                    Offer(
                        origin=offer.origin,
                        destination=offer.destination,
                        depart_date=offer.depart_date,
                        return_date=offer.return_date,
                        price_jpy=int(normal * wobble),
                        source="demo",
                    )
                ],
                observed_date=day,
            )


# -------------------------------------------------------------- test-notify


def cmd_test_notify(args) -> int:
    config = Config.load(args.config)
    target = config.active_targets[0]
    destination = target.destinations[0]
    depart = date.today() + timedelta(days=60)

    offer = Offer(
        origin=config.search.origins[0],
        destination=destination,
        depart_date=depart,
        return_date=depart + timedelta(days=7),
        price_jpy=(target.alert_price or 50_000) // 2,
        source="test",
        airline="TEST",
        transfers=0,
    )
    alert = Alert(
        offer=offer,
        reasons=["absolute"],
        messages=["これは配線確認用のテスト通知です。実際の運賃ではありません。"],
        baseline=Baseline(offer.route_key, 30, offer.price_jpy * 3, offer.price_jpy * 2, 5000.0),
        discount=0.66,
        score=0.66,
    )

    notifiers = build_notifiers(config.notifiers, config.alerting)
    if not notifiers:
        log.error("notifiers が空です。config.json に通知先を追加してください。")
        return 2

    failures = 0
    for notifier in notifiers:
        try:
            notifier.send([alert])
            print(f"✓ {notifier.type_name} に送信しました")
        except Exception as exc:
            failures += 1
            print(f"✗ {notifier.type_name} に失敗: {exc}", file=sys.stderr)
    return 1 if failures else 0


# -------------------------------------------------------------------- stats


def cmd_stats(args) -> int:
    config = Config.load(args.config)
    with Store(config.database_path) as store:
        keys = [k for k in store.route_keys() if not args.route or args.route in k]
        if not keys:
            print("履歴がまだありません。まず scan を何日か動かしてください。")
            return 0

        header = (
            _pad("路線", 30)
            + _pad("日数", 6, right=True)
            + _pad("中央値", 12, right=True)
            + _pad("25%点", 12, right=True)
            + _pad("直近", 12, right=True)
        )
        print(header)
        print("-" * _width(header))
        for key in keys:
            base = store.baseline(key, config.detection.lookback_days)
            recent = store.history(key, limit=1)
            latest = f"¥{recent[0]['price']:,}" if recent else "-"
            median = f"¥{base.median:,}" if base.median else "-"
            p25 = f"¥{base.p25:,}" if base.p25 else "-"
            ready = "" if base.samples >= config.detection.min_samples else "  相場計算まで待ち"
            print(
                _pad(key, 30)
                + _pad(str(base.samples), 6, right=True)
                + _pad(median, 12, right=True)
                + _pad(p25, 12, right=True)
                + _pad(latest, 12, right=True)
                + ready
            )

        alerts = store.recent_alerts(10)
        if alerts:
            print("\n直近の通知:")
            for row in alerts:
                print(f"  {row['sent_at'][:16]}  {row['summary']}")
    return 0


def _width(text: str) -> int:
    """全角を2文字ぶんとして数えた表示幅。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(text: str, width: int, right: bool = False) -> str:
    """表を全角混じりでも揃えるための桁合わせ。"""
    space = " " * max(width - _width(text), 0)
    return space + text if right else text + space


# -------------------------------------------------------------------- prune


def cmd_prune(args) -> int:
    config = Config.load(args.config)
    with Store(config.database_path) as store:
        removed = store.prune(args.keep_days)
        print(f"{removed} 件の古い履歴を削除しました")
    return 0
