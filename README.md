# ETF Research App

這個專案研究台灣掛牌 ETF，並提供網頁介面、命令列研究工具，以及每週自動尋找新成立 ETF 的 GitHub Actions。

## 每週新 ETF 流程

`.github/workflows/weekly-new-etfs.yml` 每週四台北時間 14:00 執行，對應 GitHub Actions 的 UTC cron `0 6 * * 4`。

1. 用瀏覽器讀取 WantGoo「成立年齡」排行，保留 `成立年齡 < 0.2` 的代碼。
2. 解析 MoneyDJ「新 ETF」排行的 `成立日期`，保留今天往前 14 天內的代碼。
3. 將兩份代碼標準化（移除 `.TW`、統一大寫）後取交集，寫入 `artifacts/new_list.txt` 與 `artifacts/new_list.json`。
4. 將 `new_list` 傳給 `etf_research_update.py`。若交集為空，只產生空的 CSV 標頭，不會浪費 Claude API 呼叫。
5. 研究結果以 GitHub Actions artifact 保存 30 天。

WantGoo 的資料是 JavaScript 動態載入且有反爬驗證，因此 collector 使用 Playwright headed Chromium；GitHub runner 透過 Xvfb 提供虛擬顯示器。若瀏覽器抓取失敗，會使用 TinyFish Agent fallback，仍然直接讀取 WantGoo 表格，不會用其他網站替代。

## GitHub Secrets

在 repository 的 Settings > Secrets and variables > Actions 新增：

- `ANTHROPIC_API_KEY`：Claude API key。
- `TINYFISH_API_KEY`：TinyFish CLI key，用於搜尋、全文抓取，以及 WantGoo fallback。

程式碼不含任何 API key；本機可以放在 `etf-app/.env`，但該檔案已列入 `.gitignore`。

## 本機執行

安裝 Python 依賴與瀏覽器後：

```bash
cd etf-app
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
python3 scripts/collect_new_etfs.py --output-dir artifacts --wantgoo-tinyfish-fallback
python3 etf_research_update.py "$(tr -d '\r\n' < artifacts/new_list.txt)"
```

如果 `new_list.txt` 是空的，請不要執行最後一行；GitHub Actions 會自動處理空集合。
