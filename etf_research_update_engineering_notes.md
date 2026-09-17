# `etf_research_update.py` 工程師說明

## 目的

`etf_research_update.py` 是台灣掛牌 ETF 的命令列研究工具。輸入一或多個 ticker 後，它會以 TinyFish 搜尋公開資料、用 URL-to-Markdown 取回選定頁面的正文，再交由 Claude Sonnet 5 產生繁中敘述與分類建議，最後輸出 UTF-8 BOM CSV。

此檔案與 `etf_research.py` 採用相同研究、分類、風險驗證與模型呼叫流程。唯一的輸出差異是移除了下列 CSV 欄位：

- `繁中名稱`
- `leveraged`
- `actively_managed`

這三個欄位仍保留在內部資料模型與 Claude 回應中。它們協助名稱正規化與分類校正，但會在寫入 CSV 時被忽略；這可縮減下游資料表欄位，而不改變研究邏輯。

## 執行方式

```bash
cd "/Users/dylan/Library/Mobile Documents/com~apple~CloudDocs/new etf/etf-app"
python3 etf_research_update.py 00405A,00642U,00991B
python3 etf_research_update.py -o etf_update_output.csv 00405A 006203 009827
```

`tickers` 支援逗號或空白分隔、會轉為大寫並去重。未指定 `-o` 時，預設輸出檔名為 `etf_output.csv`。

## 執行相依與設定

| 項目 | 用途 | 設定方式 |
| --- | --- | --- |
| Python 3 | 執行 CLI | 系統 Python 3 |
| TinyFish CLI | 搜尋 ETF 與風險等級來源 | `tinyfish` 需已登入或可使用 API key |
| URL-to-Markdown 服務 | 取得選定網址的正文 | `URL_TO_MARKDOWN_API`，預設 `http://127.0.0.1:8000` |
| Anthropic API | 產生繁中敘述與分類建議 | `ANTHROPIC_API_KEY` 環境變數或同資料夾 `.env` |

可選環境變數：

```bash
export CLAUDE_INPUT_PRICE_PER_MILLION_USD=2
export CLAUDE_OUTPUT_PRICE_PER_MILLION_USD=10
export CLAUDE_BATCH_SIZE=3
export URL_TO_MARKDOWN_TIMEOUT_SECONDS=45
```

批次大小會被限制在 1 至 3 檔。這是為了避免大量全文資料被放進同一個 prompt，導致成本、截斷或模型輸出品質失控。

## TinyFish 安裝與搜尋邏輯

本工具只透過 TinyFish CLI 做網址發現與搜尋摘要取得；網頁正文由下一階段的 URL-to-Markdown 服務處理。因此，工程師需要安裝並授權 TinyFish CLI，但不需要在此程式中設定 TinyFish 的 fetch 功能。

### 安裝與授權

```bash
npm install -g @tiny-fish/cli
tinyfish auth login --source openclaw

# 非互動式環境可改用 API key。
export TINYFISH_API_KEY="..."
```

部署或 CI 前可執行下列指令確認 CLI 位於 `PATH` 且能正常回傳 JSON：

```bash
tinyfish search query '"00405A" ETF' --language zh-TW
```

若未安裝 `tinyfish`，程式會將 subprocess 例外寫到 stderr，該 ticker 最終會被視為搜尋失敗。請在啟動工作前先完成 CLI 安裝與授權，而非依賴 CSV 的錯誤列來診斷環境問題。

### 程式呼叫行為

`search_tinyfish()` 組合下列命令：

```text
tinyfish search query <query> --language zh-TW
```

`run_tinyfish()` 透過 `subprocess.run()` 執行命令、擷取 stdout，並設有 60 秒 timeout。預期結果為 JSON；`normalize_search_results()` 會將其正規化為 `position`、`site_name`、`title`、`url` 與 `snippet`，每次最多保留八筆候選資料。若 TinyFish 回傳 429，程式會等待三秒後重試一次，以降低短暫 rate limit 造成的整批失敗。

### 每檔 ETF 的搜尋策略

1. 先執行 StockFeel 定向查詢：`"<ticker>" ETF stockfeel 股感 site:stockfeel.com.tw`。找不到符合 ticker 的文章時，改用不含 `site:` 的 StockFeel 備援查詢。
2. 接著執行原始 ETF 查詢，優先取得基金基本資料與風險報酬等級；若可用來源不足五筆，依序改用較寬鬆的 ETF 查詢。
3. 結果挑選時偏好名稱或網址含相同 ticker 的基金公司、交易所、基金資料頁與可信財經來源。社群、影音與 `cmoney.tw` 等網址不會進入 URL-to-Markdown 全文擷取清單。
4. 正常情況下保留一個 StockFeel URL 加上最多五個其他來源 URL，合計最多六個。這些 URL 會交給 URL-to-Markdown；TinyFish 搜尋摘要則保留給風險判斷與 Claude prompt。
5. 若尚未找到有效 RR 值，才以正式基金名稱及 ticker 追加 TinyFish 風險查詢，並只接受能辨識該基金的明確 RR 證據。

## 資料流程

1. 解析輸入 ticker，去除空白、重複值並統一大寫。
2. 每檔執行兩條獨立搜尋路徑：
   - StockFeel 定向搜尋：`"<ticker>" ETF stockfeel 股感 site:stockfeel.com.tw`
   - 原始 ETF／基金／風險報酬等級搜尋；若結果不足會改用較短的備援查詢。
3. 從搜尋結果選擇一個最相關的 StockFeel URL 與最多五個其他原始來源 URL。
4. 對最多六個 URL 呼叫 URL-to-Markdown，保留正文與擷取狀態。
5. 從搜尋摘要與全文中抽取可驗證的風險報酬等級；若未取得，才以基金名稱或 ticker 補查風險來源，必要時取得補查頁面正文。
6. 以產品名稱規則建立初步類別、產業、區域、商品類型、貨幣、槓桿與主動管理判斷。
7. 將每檔最多八筆搜尋摘要、每頁最多 3,000 字元且每檔最多 9,000 字元的正文證據送至 Claude。Claude 每批最多處理三檔。
8. Claude 同時回傳 ETF 分類建議與 `topic_ids`。主題判斷只可使用 prompt 中的名稱、追蹤指數、投資策略與來源證據。
9. 將 Claude 的分類建議限制在允許值集合中，再與規則式資料、已驗證產品設定及風險證據合併。
10. 以 `CSV_COLUMNS` 定義的 schema 寫出 CSV；其他內部欄位會被 `extrasaction="ignore"` 丟棄。

## 風險等級規則

`risk_rank` 是證據優先欄位，不能由 Claude 或名稱規則猜測。

- 僅接受明確的 `RR1` 至 `RR5` 指派文字。
- 來源需能識別相同 ticker，或可將基金名稱與單一 RR 值直接對應。
- 排除泛用風險分級說明、標題指向另一檔 ticker 的結果，以及 `cmoney.tw` 來源。
- 若沒有足夠證據，輸出空字串，而非填入推測值。

因此像 `00642U` 只有「高波動度」而無 RR1–RR5 的官方資料時，`risk_rank` 留白是預期行為，不代表資料處理失敗。

## 分類與產品校正

初步分類由 `pre_classify()` 依 ETF 名稱判斷，例如債券、原油、貨幣、台灣／日本／韓國／全球／美國等關鍵字。模型的輸出只能使用 `ALLOWED` 中列出的值；不合法值會回退至規則式結果。

`VERIFIED_PRODUCT_OVERRIDES` 用於搜尋結果把傘型基金誤當成子基金時的已驗證例外。目前包含 `00991B`：

```text
貝萊德iShares安碩10年期以上A級美元公司債ETF
Fixed Income / Investment Grade Corporate Bond ETFs / Global / Broad
```

這份設定會優先於 Claude 的不一致推論，確保正式名稱、債券分類與投資區域同步一致。新增例外前，應先保留官方基金公司、交易所或可辨識同 ticker 的一手來源證據。

## 主題標籤

`主題標籤` 由同一次 Claude 呼叫的 `topic_ids` 產生，不會增加額外的模型請求。主題 taxonomy 與判斷規則參考 `etf_topic_classification_prompt.md`：模型只能使用固定的 41 個 ID、可不選主題、最多五個，且不得因外部知識推斷成分股或曝險。

模型輸出後必須由 `normalize_topic_labels()` 做程式端後處理：

1. 僅保留 `TOPIC_LABELS` 中的整數 ID，丟棄無效 ID、布林值與格式錯誤的值。
2. 去除重複 ID，保留首次出現的順序。
3. 若命中人工智慧(9)、半導體(15)、景氣擴張(22)、生產力循環(26)任一項，補齊完整四項；綁定群組優先保留，最多只再保留一個其他標籤。
4. 最多保留五個 ID，映射為繁中名稱後用 `、` 串接；沒有有效 ID 時輸出空字串。

例如模型回傳 `[1, 15]`，CSV 中的結果為 `半導體、人工智慧、景氣擴張、生產力循環、乾淨能源`。這個後處理是防線的一部分，不可只信任模型已遵守綁定與 enum 規則。

## 輸出欄位

輸出順序固定如下：

| 欄位 | 說明 |
| --- | --- |
| `ticker` | 台灣 ETF 代號 |
| `主題標籤` | AI 判斷後、經程式驗證的繁中主題名稱；多個主題以 `、` 串接 |
| `zacks_category` | `Commodities`、`Currency`、`Equity` 或 `Fixed Income` |
| `zacks_sector` | 僅固定收益 ETF 使用的債券分類；其他類別留白 |
| `sector_general` | 大區域分類，例如 `Global` 或 `North America` |
| `sector_specific` | 細分區域，例如 `Taiwan`、`U.S.` 或 `Broad` |
| `commodity_type` | 僅商品 ETF 使用，例如 `Energy` |
| `currency` | 僅貨幣 ETF 使用，例如 `USD` |
| `risk_rank` | 具來源證據的 `RR1` 至 `RR5`；未證實則留白 |
| `繁中敘述` | Claude 依正文與搜尋摘要寫出的繁中 ETF 介紹 |

## 失敗處理與觀測

- 單一 ticker 搜尋失敗不會中斷整批；它仍會寫入一列，`繁中敘述` 以錯誤訊息說明。
- URL-to-Markdown 個別來源失敗時會保留失敗狀態；其他成功正文仍可供模型使用。
- 未設定 Anthropic key 時，工具略過 Claude，改用規則式分類和最小的 ETF 說明文字。
- CLI 會輸出每檔 Markdown 成功數、風險等級、TinyFish 搜尋次數，以及 Claude 的 token 和預估成本。

## 驗證建議

提交前至少執行：

```bash
python3 -m py_compile etf_research_update.py
python3 - <<'PY'
import etf_research_update as research
print(research.CSV_COLUMNS)
assert '繁中名稱' not in research.CSV_COLUMNS
assert 'leveraged' not in research.CSV_COLUMNS
assert 'actively_managed' not in research.CSV_COLUMNS
assert research.normalize_topic_labels([15]) == '半導體、人工智慧、景氣擴張、生產力循環'
PY
```

如修改搜尋、風險解析或分類規則，應用代表性樣本覆蓋台股股票、主動式 ETF、商品期貨、投資級公司債、高收益債與跨國市場 ETF，並確認每個 RR 值都有可追溯來源。
