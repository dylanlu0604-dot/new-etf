#!/usr/bin/env python3
"""Collect newly established Taiwan ETFs from WantGoo and MoneyDJ.

The two source lists are intentionally filtered independently and then
intersected by normalized ticker. WantGoo is rendered in a browser because
its ranking data is loaded by JavaScript and its API is protected by a client
signature. MoneyDJ exposes the establishment date in static table HTML.
"""

from __future__ import annotations

import argparse
import certifi
import json
import os
import re
import ssl
import subprocess
import sys
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


WANTGOO_URL = "https://www.wantgoo.com/stock/etf/ranking/age"
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


def parse_float(value: str) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    return float(match.group(0)) if match else None


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
            print(f"TLS verification warning for {url}: {exc}", file=sys.stderr)
            with urlopen(request, timeout=timeout, context=ssl._create_unverified_context()) as response:
                return response.read().decode("utf-8", errors="replace")
        raise


def collect_moneydj(today: date, lookback_days: int) -> list[dict[str, Any]]:
    html = fetch_text(MONEYDJ_URL)
    parser = MoneyDJRowParser()
    parser.feed(html)
    start_date = today - timedelta(days=lookback_days)
    items: list[dict[str, Any]] = []
    for row in parser.rows:
        ticker = normalize_ticker(row.get("col01", ""))
        if not TICKER_RE.fullmatch(ticker):
            continue
        try:
            established = datetime.strptime(row["col05"], "%Y/%m/%d").date()
        except ValueError:
            continue
        if start_date <= established <= today:
            items.append(
                {
                    "ticker": ticker,
                    "name": row.get("col02", ""),
                    "established_date": established.isoformat(),
                }
            )
    return items


def extract_tinyfish_result(raw: str) -> Any:
    """Extract resultJson from either JSON or SSE output from TinyFish."""
    candidates: list[Any] = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line:
            continue
        try:
            candidates.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    for item in reversed(candidates):
        if isinstance(item, dict) and item.get("resultJson") is not None:
            result = item["resultJson"]
            if isinstance(result, str):
                try:
                    return json.loads(result)
                except json.JSONDecodeError:
                    return None
            return result
        if isinstance(item, (list, dict)):
            return item
    return None


def collect_wantgoo_with_tinyfish() -> list[dict[str, Any]]:
    goal = (
        "Navigate the page and extract every visible Taiwan ETF row whose "
        "成立年齡 is strictly less than 0.2. Return JSON only as "
        "{\"items\":[{\"ticker\":\"string\",\"age\":number,\"name\":\"string\"}]} . "
        "Read the table itself; do not infer from search snippets."
    )
    try:
        result = subprocess.run(
            ["tinyfish", "agent", "run", "--url", WANTGOO_URL, goal, "--sync"],
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"TinyFish WantGoo fallback failed: {exc}") from exc
    payload = extract_tinyfish_result(result.stdout)
    raw_items = payload.get("items", []) if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        return []
    items: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        ticker = normalize_ticker(item.get("ticker", ""))
        age = parse_float(str(item.get("age", "")))
        if TICKER_RE.fullmatch(ticker) and age is not None and age < 0.2:
            items.append({"ticker": ticker, "age": age, "name": str(item.get("name", ""))})
    return items


def collect_wantgoo() -> list[dict[str, Any]]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required for WantGoo. Install requirements.txt first."
        ) from exc

    try:
        with sync_playwright() as playwright:
            # GitHub Actions runs this script under xvfb so Chromium is headed;
            # local terminal runs without DISPLAY and use headless Chromium.
            browser = playwright.chromium.launch(
                headless=not bool(__import__("os").environ.get("DISPLAY")),
                args=["--disable-blink-features=AutomationControlled"],
            )
            browser_major = browser.version.split(".", 1)[0]
            context = browser.new_context(
                locale="zh-TW",
                viewport={"width": 1440, "height": 1200},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    f"(KHTML, like Gecko) Chrome/{browser_major}.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.goto(WANTGOO_URL, wait_until="domcontentloaded", timeout=90_000)
            rows = page.locator("#ranking tr")
            rows.first.wait_for(state="attached", timeout=90_000)
            items: list[dict[str, Any]] = []
            for index in range(rows.count()):
                row = rows.nth(index)
                cells = row.locator("td").all_text_contents()
                links = row.locator("a").all_text_contents()
                if len(cells) < 3 or not links:
                    continue
                ticker = normalize_ticker(links[0])
                age = parse_float(cells[-1])
                if TICKER_RE.fullmatch(ticker) and age is not None and age < 0.2:
                    items.append({"ticker": ticker, "age": age, "name": links[1] if len(links) > 1 else ""})
            context.close()
            browser.close()
            if items:
                return items
            raise RuntimeError("WantGoo page loaded but returned no ranking rows")
    except Exception as exc:
        if isinstance(exc, RuntimeError) and str(exc).startswith("WantGoo page loaded"):
            raise
        if "PlaywrightTimeoutError" in type(exc).__name__ or isinstance(exc, PlaywrightTimeoutError):
            raise RuntimeError(f"WantGoo browser timed out: {exc}") from exc
        raise RuntimeError(f"WantGoo browser extraction failed: {exc}") from exc


def write_outputs(output_dir: Path, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "new_list.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "new_list.txt").write_text(
        ",".join(payload["new_list"]) + "\n", encoding="utf-8"
    )


def derive_wantgoo_age_items(moneydj_items: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """Derive the WantGoo age condition when Cloudflare blocks its browser.

    Every MoneyDJ item selected by the 14-day condition is necessarily younger
    than 0.2 years (about 73 days), so this preserves the requested set
    intersection while keeping the fallback explicit in the output metadata.
    """
    items: list[dict[str, Any]] = []
    for item in moneydj_items:
        established = date.fromisoformat(item["established_date"])
        age = (today - established).days / 365.25
        if age < 0.2:
            items.append({"ticker": item["ticker"], "age": round(age, 4), "name": item.get("name", "")})
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="找出兩個 ETF 網站的新成立 ETF 交集")
    parser.add_argument("--output-dir", default="artifacts")
    parser.add_argument("--lookback-days", type=int, default=14)
    parser.add_argument("--today", help="測試用 YYYY-MM-DD；未提供時使用台北日期")
    parser.add_argument("--wantgoo-tinyfish-fallback", action="store_true")
    parser.add_argument(
        "--wantgoo-derived-fallback",
        action="store_true",
        help="WantGoo 被 Cloudflare 擋住時，以 MoneyDJ 14 天日期推導成立年齡條件",
    )
    args = parser.parse_args()

    today = date.fromisoformat(args.today) if args.today else datetime.now(TAIPEI).date()
    moneydj_items = collect_moneydj(today, args.lookback_days)
    wantgoo_warning = ""
    wantgoo_source = "wantgoo-browser"
    if not moneydj_items:
        # The requested result is an intersection. When MoneyDJ contributes no
        # rows, no WantGoo row can belong to new_list, so avoid an unnecessary
        # browser/TinyFish request and still produce a valid empty artifact.
        wantgoo_items = []
        wantgoo_source = "not-needed-empty-moneydj-filter"
        wantgoo_warning = (
            "MoneyDJ returned no ETFs within the lookback window; "
            "the intersection is necessarily empty"
        )
    else:
        try:
            wantgoo_items = collect_wantgoo()
        except RuntimeError as exc:
            wantgoo_warning = str(exc)
            if not args.wantgoo_tinyfish_fallback:
                raise
            print(f"WantGoo browser warning: {exc}; using TinyFish agent fallback", file=sys.stderr)
            wantgoo_items = collect_wantgoo_with_tinyfish()
            if not wantgoo_items:
                wantgoo_warning += "; TinyFish returned no rows"

    if not wantgoo_items and args.wantgoo_derived_fallback and moneydj_items:
        print(
            "WantGoo did not return rows; deriving its <0.2 age set from "
            "MoneyDJ's already-selected 14-day set.",
            file=sys.stderr,
        )
        wantgoo_items = derive_wantgoo_age_items(moneydj_items, today)
        wantgoo_source = "derived-from-moneydj-14-day-filter"
    elif (
        not wantgoo_items
        and wantgoo_warning
        and wantgoo_source != "not-needed-empty-moneydj-filter"
    ):
        raise RuntimeError(f"WantGoo extraction failed: {wantgoo_warning}")

    wantgoo_by_ticker = {item["ticker"]: item for item in wantgoo_items}
    moneydj_by_ticker = {item["ticker"]: item for item in moneydj_items}
    new_list = [ticker for ticker in wantgoo_by_ticker if ticker in moneydj_by_ticker]
    payload = {
        "generated_at": datetime.now(TAIPEI).isoformat(),
        "as_of_date": today.isoformat(),
        "wantgoo_filter": "成立年齡 < 0.2",
        "moneydj_filter": f"成立日期 >= {today - timedelta(days=args.lookback_days)}",
        "wantgoo_source": wantgoo_source,
        "wantgoo_warning": wantgoo_warning,
        "wantgoo": list(wantgoo_by_ticker.values()),
        "moneydj": list(moneydj_by_ticker.values()),
        "new_list": new_list,
    }
    write_outputs(Path(args.output_dir), payload)
    print(json.dumps({"new_list": new_list, "wantgoo_count": len(wantgoo_items), "moneydj_count": len(moneydj_items)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
