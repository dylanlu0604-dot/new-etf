#!/usr/bin/env python3
"""Check the complete weekly CSV before it is uploaded or committed."""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from etf_research_update import ALLOWED, CSV_COLUMNS, REGION_SPECIFIC_BY_GENERAL, TOPIC_LABELS, validate_description


def validate(csv_path, ticker_path):
    expected = [ticker.strip().upper() for ticker in ticker_path.read_text(encoding="utf-8-sig").replace("，", ",").split(",") if ticker.strip()]
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != CSV_COLUMNS:
            raise ValueError(f"CSV columns differ from expected schema: {reader.fieldnames}")
        rows = list(reader)
    tickers = [row["ticker"].strip().upper() for row in rows]
    if len(set(tickers)) != len(tickers) or tickers != expected:
        raise ValueError(f"CSV tickers {tickers} do not match new_list {expected}")
    known_topics = set(TOPIC_LABELS.values())
    lengths = []
    for row in rows:
        ticker = row["ticker"]
        issues, stats = validate_description(row["繁中敘述"])
        if issues:
            raise ValueError(f"{ticker}: description invalid: {issues}; stats={stats}")
        lengths.append(stats["characters"])
        for field in ("zacks_category", "region_general", "region_specific"):
            if row[field] not in ALLOWED[field]:
                raise ValueError(f"{ticker}: invalid {field}={row[field]!r}")
        if row["region_specific"] not in REGION_SPECIFIC_BY_GENERAL[row["region_general"]]:
            raise ValueError(f"{ticker}: conflicting region fields")
        for field in ("zacks_sector", "commodity_type", "currency", "risk_rank"):
            if row[field] and row[field] not in ALLOWED[field]:
                raise ValueError(f"{ticker}: invalid {field}={row[field]!r}")
        if row["zacks_category"] != "Fixed Income" and row["zacks_sector"]:
            raise ValueError(f"{ticker}: zacks_sector requires Fixed Income")
        if row["zacks_category"] != "Commodities" and row["commodity_type"]:
            raise ValueError(f"{ticker}: commodity_type requires Commodities")
        if row["zacks_category"] != "Currency" and row["currency"]:
            raise ValueError(f"{ticker}: currency requires Currency")
        topics = [topic for topic in row["主題標籤"].split("、") if topic]
        if len(topics) > 5 or len(set(topics)) != len(topics) or any(topic not in known_topics for topic in topics):
            raise ValueError(f"{ticker}: invalid topic labels {topics}")
    return len(rows), min(lengths, default=0), max(lengths, default=0)


if __name__ == "__main__":
    count, minimum, maximum = validate(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"Validated {count} ETF rows; description lengths {minimum}–{maximum} non-whitespace characters")
