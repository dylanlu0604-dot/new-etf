#!/usr/bin/env python3
"""Collect newly established Taiwan ETFs from MoneyDJ."""

from __future__ import annotations

import argparse
import certifi
import json
import re
import ssl
import sys
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


MONEYDJ_URL = (
    "https://www.moneydj.com/etf/x/rank/rank0005.xdjhtm?"
    "erank=new&eord=t100050&esort=1"
)
TAIPEI = ZoneInfo("Asia/Taipei")
TICKER_RE = re.compile(r"^\d{4,6}[A-Z]?$", re.IGNORECASE)


def normalize_ticker(value: str) -> str:
    """Normalize source formats such as 009827.TW to 009827."""
    ticker = re.sub(r"\.TW$", "", str(value or "").strip(), flags=re.IGNORECASE)
    return ticker.upper()


class MoneyDJRowParser(HTMLParser):
    """Read the table cells by their stable MoneyDJ column classes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, str]] = []
        self._row: dict[str, str] | None = None
        self._cell_class = ""
        self._cell_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if tag == "tr":
            self._row = {}
        elif tag == "td" and self._row is not None:
            self._cell_class = attrs_map.get("class") or ""
            self._cell_text = []

    def handle_data(self, data: str) -> None:
        if self._row is not None and self._cell_class:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._row is not None and self._cell_class:
            self._row[self._cell_class] = " ".join("".join(self._cell_text).split())
            self._cell_class = ""
            self._cell_text = []
        elif tag == "tr" and self._row:
            if self._row.get("col01") and self._row.get("col05"):
                self.rows.append(self._row)
            self._row = None


def fetch_text(url: str, timeout: int = 60) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        },
    )
    context = ssl.create_default_context(cafile=certifi.where())
    try:
        with urlopen(request, timeout=timeout, context=context) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        # Some locally installed macOS trust stores reject the public proxy
        # certificate used by this source. GitHub's Ubuntu runner uses the
        # verified path above; this fallback keeps local diagnostics usable.
        if isinstance(exc, OSError) and "CERTIFICATE_VERIFY_FAILED" in str(exc):
            print(f"WARNING: TLS verification fallback for {url}: {exc}", file=sys.stderr)
            with urlopen(request, timeout=timeout, context=ssl._create_unverified_context()) as response:
                return response.read().decode("utf-8", errors="replace")
        raise


def collect_moneydj(today: date, lookback_days: int) -> list[dict[str, Any]]:
    html = fetch_text(MONEYDJ_URL)
    parser = MoneyDJRowParser()
    parser.feed(html)
    if not parser.rows:
        raise RuntimeError("MoneyDJ page returned no recognizable ETF rows")
    start_date = today - timedelta(days=lookback_days)
    items: list[dict[str, Any]] = []
    candidate_rows = 0
    parsed_date_rows = 0
    for row in parser.rows:
        ticker = normalize_ticker(row.get("col01", ""))
        if not TICKER_RE.fullmatch(ticker):
            continue
        candidate_rows += 1
        try:
            established = datetime.strptime(row["col05"], "%Y/%m/%d").date()
        except ValueError:
            continue
        parsed_date_rows += 1
        if start_date <= established <= today:
            items.append(
                {
                    "ticker": ticker,
                    "name": row.get("col02", ""),
                    "established_date": established.isoformat(),
                }
            )
    if not candidate_rows:
        raise RuntimeError("MoneyDJ page contained no valid ETF tickers")
    if not parsed_date_rows:
        raise RuntimeError("MoneyDJ page contained no parseable establishment dates")
    return items


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "new_list.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "new_list.txt").write_text(
        ",".join(payload["new_list"]) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="找出 MoneyDJ 近14天成立的新 ETF")
    parser.add_argument("--output-dir", default="artifacts")
    parser.add_argument("--lookback-days", type=int, default=14)
    parser.add_argument("--today", help="測試用 YYYY-MM-DD；未提供時使用台北日期")
    args = parser.parse_args()

    today = date.fromisoformat(args.today) if args.today else datetime.now(TAIPEI).date()
    try:
        moneydj_items = collect_moneydj(today, args.lookback_days)
    except Exception as exc:
        warning = f"MoneyDJ crawler failed: {exc}"
        print(f"WARNING: {warning}", file=sys.stderr)
        raise RuntimeError(warning) from exc

    new_list = list(dict.fromkeys(item["ticker"] for item in moneydj_items))
    payload = {
        "generated_at": datetime.now(TAIPEI).isoformat(),
        "as_of_date": today.isoformat(),
        "moneydj_filter": f"成立日期 >= {today - timedelta(days=args.lookback_days)}",
        "source": "moneydj-only",
        "crawler_warnings": [],
        "moneydj": moneydj_items,
        "new_list": new_list,
    }
    write_outputs(Path(args.output_dir), payload)
    print(json.dumps({
        "new_list": new_list,
        "moneydj_count": len(moneydj_items),
        "crawler_warnings": [],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
