#!/usr/bin/env python3
"""Fetch public MoneyDJ ETF records and official product URLs for the supplied ticker list."""
import json, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
TICKERS = (ROOT / "artifacts/tickers_full.txt").read_text().splitlines()
OUT = ROOT / "artifacts/moneydj_sources.json"

def fetch(ticker):
    url = f"https://www.moneydj.com/ETF/X/Basic/Basic0004.xdjhtm?etfid={ticker}.TW"
    rec = {"ticker": ticker, "moneydj_url": url, "status": "error"}
    try:
        r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=30)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.select_one("table#sTable")
        if not table:
            return {**rec, "error": "missing data table", "http_status": r.status_code}
        rows = []
        for tr in table.select("tr"):
            cells = [x.get_text(" ", strip=True) for x in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        data = {}
        for row in rows:
            if len(row) >= 2:
                data[row[0]] = row[1]
            if len(row) >= 4:
                data[row[2]] = row[3]
        title = ""
        title_node = soup.select_one("div.Title")
        if title_node:
            title = title_node.get_text(" ", strip=True)
        rec.update({
            "status": "ok", "http_status": r.status_code, "title": title,
            "name": data.get("ETF名稱", ""), "issuer": data.get("發行公司", ""),
            "established_date": data.get("成立日期", "").split("（")[0].strip(),
            "listing_date": data.get("上市日期", ""), "manager": data.get("經理人", ""),
            "region": data.get("投資區域", ""), "target": data.get("投資標的", ""),
            "style": data.get("投資風格", ""), "strategy": data.get("投資策略", ""),
            "management_fee": data.get("經理費(%)", ""), "total_fee": data.get("總管理費用(%)", ""),
            "official_url": data.get("官方網站連結", ""),
            "tracking_index": data.get("追蹤指數", ""), "benchmark": data.get("基準指數", ""),
        })
        return rec
    except Exception as e:
        return {**rec, "error": str(e)}

def main():
    out = [None] * len(TICKERS)
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(fetch, t): i for i, t in enumerate(TICKERS)}
        for n, fut in enumerate(as_completed(futures), 1):
            out[futures[fut]] = fut.result()
            if n % 25 == 0 or n == len(TICKERS):
                print(f"fetched {n}/{len(TICKERS)}", file=sys.stderr)
    OUT.write_text(json.dumps({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "records": out}, ensure_ascii=False, indent=2) + "\n")
    ok = sum(x.get("status") == "ok" for x in out)
    print(json.dumps({"count": len(out), "ok": ok, "errors": len(out)-ok, "output": str(OUT)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
