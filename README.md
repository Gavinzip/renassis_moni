# Renaiss 真實市價即時監控系統 (極速實時版)

這是一套為 AI Agent 設計的 **「全實時、零延遲」** 市場監控系統。它的核心目的是透過整合 PriceCharting 與 SNKRDUNK 的即時成交數據，第一時間發現 Renaiss 平台上的低價撿漏機會。

---

## 📂 系統架構：純實時（No-DB）

本系統不依賴任何資料庫，完全基於「現場抓取、現場分析」的邏輯運作：

1. **`market_report_vision.py` (爬蟲引擎)**
   - 負責動態獲取卡片的即時報價。
   - **SNKRDUNK**：直接呼叫原生 API，確保高準確度。
   - **PriceCharting**：透過 BeautifulSoup/Jina 獲取當前成交紀錄。

2. **`market_monitor.py` (監控中心)**
   - 主程序，建議 24 小時在背景運行。
   - **30天滾動均價**：系統僅獲取最近 30 天內的成交紀錄，確保反映當前熱度。
   - **雙來源獨立判斷**：分別計算 PC 與 SNKR 的均價，只要任一來源便宜超過 $30 USD 即觸發警報。
   - **實時比價**：每 5 分鐘掃描 Renaiss，針對每一筆掛單立即發動爬蟲。
   - **記憶體計算**：直接在記憶體中計算四分位距 (IQR) 均價，不落地存儲。

---

## 🚀 啟動與維運指南

### 1. 為什麼我需要 API Key (Minimax/OpenAI)？
雖然抓取價格是免費的，但當監控器發現一張標題模糊的「新卡片」時，需要 AI 大腦去識別圖片或標題。這是為了確保搜尋關鍵字正確，避免抓錯價格。

### 2. 快速啟動
切換至目錄並設定環境變數：

```bash
# 1. 警報接收 (必填)
export DISCORD_WEBHOOK_URL="你的_WEBHOOK_網址"

# 2. 自定義監控參數 (選填)
export WINDOW_DAYS=30        # 均價計算時間範圍 (預設 30 天)
export PRICE_THRESHOLD=30.0  # 觸發警報的價差門檻 (預設 $30 USD)

# 背景啟動
python3 -m pip install -r requirements.txt
nohup python3 -u market_monitor.py > market_monitor.log 2>&1 &
```

---

## 🔔 警報機制

### Discord 即時推送
當系統發現 **「市場均價 - 賣家開價 ≥ $30 USD」** 時，會立刻發送精美的 Embed 訊息到 Discord，包含：
- 卡片名稱、等級
- 賣家開價 vs 市場真實均價
- 直接跳轉到比價平台的連結

### 日誌監控
你可以隨時查看日誌：
`tail -f market_monitor.log`
只要日誌中出現 `🚨 [真正撿漏警報]`，就是進場買入的時機！

---

## 🛡 錯誤排除
- **連線失敗**：若遇到網路波動導致爬蟲超時，系統會自動略過該卡片並在下一輪重試，不會崩潰。
- **遺漏卡片**：若 Renaiss 標題過於簡略，請確保設定了正確的 AI API Key 以利 Vision 引擎辨識。
