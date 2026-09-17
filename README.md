# ETF Research App

這個專案研究台灣掛牌 ETF，並提供網頁介面、命令列研究工具，以及每週自動尋找新成立 ETF 的 GitHub Actions。

## 每週新 ETF 流程

`.github/workflows/weekly-new-etfs.yml` 每週四台北時間 14:00 執行，對應 GitHub Actions 的 UTC cron `0 6 * * 4`。

1. 解析 MoneyDJ「新 ETF」排行的 `成立日期`，保留今天往前 14 天內的代碼。
2. 將代碼標準化（移除 `.TW`、統一大寫）後寫入 `artifacts/new_list.txt` 與 `artifacts/new_list.json`。
3. 將 `new_list` 傳給 `etf_research_update.py`。若清單為空，只產生空的 CSV 標頭，不會浪費 Claude API 呼叫。
4. 研究結果寫入 repository 的 `artifacts/` 固定目錄，並另外以 GitHub Actions artifact 保存 30 天。

collector 只使用 MoneyDJ 的靜態表格，不再依賴 WantGoo、Playwright 或 TinyFish。若 MoneyDJ 網路請求失敗、頁面沒有可辨識的 ETF 列、代碼無效，或成立日期無法解析，log 會輸出 `WARNING` 並停止，避免產生不完整資料。執行結果會在 `new_list.json` 的 `crawler_warnings` 保留警告欄位。

## GitHub Secrets

在 repository 的 Settings > Secrets and variables > Actions 新增：

- `ANTHROPIC_API_KEY`：Claude API key。
- `TINYFISH_API_KEY`：TinyFish CLI key，用於 ETF 研究的搜尋與全文抓取。

程式碼不含任何 API key；本機可以放在 `etf-app/.env`，但該檔案已列入 `.gitignore`。

## 本機執行

安裝 Python 依賴與瀏覽器後：

```bash
cd etf-app
python3 -m pip install -r requirements.txt
python3 scripts/collect_new_etfs.py --output-dir artifacts
python3 etf_research_update.py "$(tr -d '\r\n' < artifacts/new_list.txt)"
```

如果 `new_list.txt` 是空的，請不要執行最後一行；GitHub Actions 會自動處理空集合。
