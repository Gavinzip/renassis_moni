# Renaiss 真實市價即時監控系統 (AI Agent 運行手冊)

這是一套為 AI Agent 設計的 24 小時全自動化監控與資料庫維護系統。它的核心目的是**「透過真實成交均價 (PriceCharting / SNKRDUNK) 來即時尋找 Renaiss 平台上的漏網特價卡」**，並同時維護一個不間斷更新的卡片行情 SQLite 資料庫。

---

## 📂 系統核心架構

本系統由兩大核心引擎組成：

### 為什麼我需要 API Key (Minimax/OpenAI)？
雖然抓取價格是免費的，但當監控器發現一張「新卡片」時，需要 AI 大腦去分析圖片或掛單標題，提取正確的編號。沒有這個「辨識階段」，系統就不知道要去 PriceCharting 搜尋哪張卡。

1. **`renaiss_full_db.sqlite` (中央資料庫)**
   - 包含兩張主要的資料表：
     - `cards`：儲存卡片的基本資訊 (名稱、編號、彈別、評級、官方買回價、最後更新時間)。
     - `price_history`：儲存該卡片在外部平台 (PriceCharting, SNKRDUNK) 近一年的真實歷史成交價。

2. **`main/market_report_vision.py` (爬蟲引擎)**
   - 負責動態去網路上獲取卡片的即時報價。
   - **SNKRDUNK**：直接呼叫原生 API (`/v1/search`, `trading-histories`)，預設抓取最新的 100 筆紀錄，具備極高的準確度及防封鎖能力。
   - **PriceCharting**：透過 BeautifulSoup/Jina 等機制進行抓取。

3. **`renassis/market_monitor.py` (實時監控大腦)**
   - 這是你需要讓 AI Agent **全天候 24 小時在背景運行** 的主程式。

---

## 🤖 `market_monitor.py` 的核心：全實時監控 (Full Real-Time)

系統目前已升級為 **「全實時 (Full Real-Time)」** 模式，這意味著 Agent 啟動後將進行以下自動化流程：

### 功能一：實時撿漏分析 (Real-Time Crawl-then-Analyze)
- **運作方式**：每 5 分鐘掃描一次 Renaiss 平台。
- **動態抓取**：針對掃描到的**每一筆**掛單，機器人會立即發動一次全新的 PriceCharting 或 SNKRDUNK 爬蟲（透過 `mrv` 引擎）。
- **零資料庫依賴比價**：警告不再依賴資料庫裡的舊平均價，而是直接拿「當場抓到」的最新成交紀錄來計算。
- **四分位距 (IQR) 過濾**：自動剔除離群值，算出最真實的「當下市場均價」，並與賣家開價比對。

### 功能二：變體精準對位 (Variant Mapping)
- **自動對應**：系統能辨識 `l-p` (魯夫限定版)、`sr-p`、`manga` (漫畫圖) 等特殊標記。
- **精準查價**：大腦會指示爬蟲降落在正確的 Variant 頁面（如 `alternate-art`），確保「異圖卡」不會被誤判為「普卡」。

### 功能三：輕量化資料庫持久化
- **異步記錄**：雖然報警是實時的，但每次抓回來的最新價格仍會寫入 `renaiss_full_db.sqlite`，為未來的數據分析、漲幅排行提供資料基礎。


---

## 🚀 AI Agent 啟動與維運指南

### 1. 系統環境準備
請確保這個 Repository (專案資料夾) 包含了這兩個核心目錄：
- `main/` (包含爬蟲引擎 `market_report_vision.py`)
- `renassis/` (包含大腦 `market_monitor.py` 和資料庫 `renaiss_full_db.sqlite`)

### 2. 啟動與維運
切換至 `renassis` 資料夾，設定環境變數並啟動：
```bash
# 設定 Discord Webhook (選填，若有設定則會發送警報至頻道)
export DISCORD_WEBHOOK_URL="你的_WEBHOOK_網址"

python3 -m pip install -r requirements.txt
nohup python3 -u market_monitor.py > market_monitor.log 2>&1 &
```
- `-u` 參數確保 log 實時寫入，方便 Agent 讀取。
- `market_monitor.log` 中若出現 `🚨 [真正撿漏警報]`，即為進場時機。


### 2. 監控與警報對接
你的 AI Agent 可以持續讀取（`tail -f market_monitor.log`）輸出日誌。
- 只要偵測到日誌中出現 `🚨 [真正撿漏警報]` 的字眼，就可以立刻觸發 Webhook 或提醒機制。
- 這個字眼後方會跟著：卡片名稱、賣家開價、真實市場均價、折扣百分比。

### 3. 未來擴充：報表生成
目前在 `market_monitor.py` 啟動時，會自動跑一次 `generate_report()` 函數，印出近期市場上漲幅最大的榜單。
如需「每週報告」或「每月報告」，AI Agent 可以隨時撰寫額外的 Python 腳本去 Query `price_history` 和 `listings` 資料表：
- `SELECT * FROM price_history WHERE item_id = '...' ORDER BY date DESC`
- 可用來繪製折線圖或匯出成 CSV 交給群組。

---

## 🛡 狀態與錯誤排除
- **如果遇到 `ConnectionError`**：通常是因為網路波動，`requests` 在爬網頁時超時。腳本內部的迴圈已包含 `try/except`，遇到此狀況會自動略過該回合，並在 5 分鐘後重新嘗試，**不會導致系統崩潰 (Crash)**。
- **若需強制重抓某卡**：直接使用 SQLite 工具，把該卡片在 `cards` 資料表中的 `last_updated` 欄位改成 10 年前 (或設為 NULL)，監控器在下一次循環的「三日無感更新」就會優先把它抓出來重新爬一次。
