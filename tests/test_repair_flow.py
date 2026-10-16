import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import etf_research_update as research
from scripts.validate_research_csv import validate as validate_csv


def description(label):
    clauses = [
        "基金以公開說明書列明的投資範圍為主要依據，研究時應逐項核對指數或策略與資料日期，並將市場曝險與投資方法清楚區分",
        "投資組合的配置需要依照最新公告及持倉報告確認，不能把募集前的預擬標的或指數成分直接寫成基金實際買進的證券",
        "費用、收益分配與風險等級各有不同的來源和生效條件，敘述時應保留原始公告的計算基準、觀察期間與適用範圍",
        "投資人閱讀資料時可分別檢視基金的資產類別、區域分布與運作方式，並確認揭露數值所對應的日期及文件版本",
    ]
    return "".join(f"{label}{part}，並同時查核資料來源的揭露時間及實際適用範圍，相關說明均應以基金正式文件揭露的內容為準。" for part in clauses)


class RepairFlowTest(unittest.TestCase):
    def test_unpublished_boolean_fields_do_not_block_audit(self):
        for field in ("leveraged", "actively_managed"):
            self.assertNotIn(field, research.CSV_COLUMNS)
            self.assertNotIn(field, research.OPENAI_RESULT_PROPERTIES)
            self.assertNotIn(field, research.build_openai_fact_check_prompt("source", []).split("原始來源任務：")[0])

    def test_only_failed_ticker_is_regenerated(self):
        tickers = ["00416A", "00415A"]
        names = {tickers[0]: "測試基金甲", tickers[1]: "測試基金乙"}
        first_description = description("甲")
        second_description = description("乙")
        repaired_description = description("修")
        self.assertFalse(research.validate_description(first_description)[0])

        def source(ticker):
            return {
                "ticker": ticker, "etfName": names[ticker], "verifiedProduct": {},
                "pre": research.pre_classify(ticker, names[ticker]),
                "tinyfishResults": [], "markdownResults": [], "selectedUrls": [],
                "searchAttempts": 1,
            }

        def candidate(ticker, body):
            return {
                "ticker": ticker, "繁中名稱": names[ticker], "繁中敘述": body,
                "zacks_category": "Equity", "zacks_sector": "",
                "region_general": "Emerging Asia Pacific", "region_specific": "Taiwan",
                "commodity_type": "", "currency": "", "risk_rank": "", "topic_ids": [],
            }

        research_prompts = []
        audit_prompts = []

        def fake_openai(prompt, response_format=research.OPENAI_RESPONSE_TEXT_FORMAT):
            if response_format == research.OPENAI_AUDIT_TEXT_FORMAT:
                audit_prompts.append(prompt)
                results = ([
                    {"ticker": tickers[0], "approved": True, "issues": []},
                    {"ticker": tickers[1], "approved": False, "issues": ["修正來源事實"]},
                ] if len(audit_prompts) == 1 else [
                    {"ticker": tickers[1], "approved": True, "issues": []},
                ])
            else:
                research_prompts.append(prompt)
                results = ([candidate(tickers[0], first_description), candidate(tickers[1], second_description)]
                           if len(research_prompts) == 1 else [candidate(tickers[1], repaired_description)])
            return {"text": json.dumps({"results": results}, ensure_ascii=False),
                    "input_tokens": 1, "output_tokens": 1, "cost_usd": 0}

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "result.csv"
            diagnostics = Path(temp) / "diagnostics.json"
            with patch.object(research, "OPENAI_API_KEY", "fake"), \
                 patch.object(research, "research_ticker", side_effect=source), \
                 patch.object(research, "call_openai", side_effect=fake_openai), \
                 patch.object(research.time, "sleep"), \
                 patch.object(sys, "argv", ["etf_research_update.py", "-o", str(output), ",".join(tickers)]), \
                 patch.dict(os.environ, {"ETF_RESEARCH_DIAGNOSTICS": str(diagnostics)}):
                research.main()
            with output.open(newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["ticker"] for row in rows], tickers)
            self.assertEqual(rows[0]["繁中敘述"], first_description)
            self.assertEqual(rows[1]["繁中敘述"], repaired_description)
            self.assertEqual(len(research_prompts), 2)
            self.assertIn("Ticker: 00416A", research_prompts[0])
            self.assertNotIn("Ticker: 00416A", research_prompts[1])
            self.assertEqual(json.loads(diagnostics.read_text())["status"], "complete")
            ticker_path = Path(temp) / "new_list.txt"
            ticker_path.write_text(",".join(tickers), encoding="utf-8")
            self.assertEqual(validate_csv(output, ticker_path)[0], 2)

    def test_duplicate_audit_records_are_rejected(self):
        tickers = ["00416A", "00415A"]
        audit = [{"ticker": "00416A", "approved": True, "issues": []}] * 2
        self.assertEqual(research.validate_openai_fact_check(tickers, audit)[0]["ticker"], "batch")


if __name__ == "__main__":
    unittest.main()
