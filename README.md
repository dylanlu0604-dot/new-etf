# ETF Research App

這個專案研究台灣掛牌 ETF，並提供網頁介面、命令列研究工具，以及每週自動尋找新成立 ETF 的 GitHub Actions。

## 每週新 ETF 流程

`.github/workflows/weekly-new-etfs.yml` 每週四台北時間 14:00 執行，對應 GitHub Actions 的 UTC cron `0 6 * * 4`。

1. 解析 MoneyDJ「新 ETF」排行的 `成立日期`，保留今天往前 14 天內的代碼。
2. 將代碼標準化（移除 `.TW`、統一大寫）後寫入 `artifacts/new_list.txt` 與 `artifacts/new_list.json`。
3. 將 `new_list` 傳給 `etf_research_update.py`。若清單為空，只產生空的 CSV 標頭，不會浪費 OpenAI API 呼叫。
4. 每檔分開生成與查核；查核退回時只自動修正該檔，已通過者保留。最後驗證整份 CSV 的代碼、欄位、敘述長度與分類，再提交到 `main`。
5. Action 一律上傳 `artifacts/` 與 `research_diagnostics.json`，並在摘要顯示每檔狀態。研究失敗時不提交舊 CSV，診斷仍可下載；成功結果保留 30 天。

collector 只使用 MoneyDJ 的靜態表格，不再依賴 WantGoo、Playwright 或 TinyFish。若 MoneyDJ 網路請求失敗、頁面沒有可辨識的 ETF 列、代碼無效，或成立日期無法解析，log 會輸出 `WARNING` 並停止，避免產生不完整資料。執行結果會在 `new_list.json` 的 `crawler_warnings` 保留警告欄位。

## GitHub Secrets

在 repository 的 Settings > Secrets and variables > Actions 新增：

- `OPENAI_API_KEY`：OpenAI API key。
- `TINYFISH_API_KEY`：TinyFish CLI key，用於 ETF 研究的搜尋與全文抓取。

程式碼不含任何 API key；本機可以放在 `etf-app/.env`，但該檔案已列入 `.gitignore`。
研究使用 OpenAI Responses API，預設模型為 `gpt-6-luna`；敘述目標約 400 至 500 字，至少 360 個非空白字元、220 個中文字及 4 句不重複的完整句子。敘述須清楚區分實際持倉、指數成分股、募集時預擬配置與例示標的；若持倉資料早於基金成立日，不得描述為基金實際持倉；不配息基金不可推薦給以領息為目標的投資人；日期依來源保留年份。Action 每次只處理一檔，品質驗收失敗時會依具體原因在同一次執行中自動重試最多四次；仍未達標就停止，不會發布未查核的短句。可用 `OPENAI_MODEL` 覆寫模型名稱。GitHub Actions 需在 Secrets 中設定有效的 `OPENAI_API_KEY`。

每週研究只讓模型產生並查核實際會寫入 CSV 的分類。`leveraged`、`actively_managed` 不在此 CSV 中，也不會因為缺乏「完全不使用槓桿」的證明而阻擋結果；敘述本身提到槓桿時仍須有來源支持。

## 本機執行

安裝 Python 依賴與瀏覽器後：

```bash
cd etf-app
python3 -m pip install -r requirements.txt
python3 scripts/collect_new_etfs.py --output-dir artifacts
python3 etf_research_update.py "$(tr -d '\r\n' < artifacts/new_list.txt)"
```

如果 `new_list.txt` 是空的，請不要執行最後一行；GitHub Actions 會自動處理空集合。
