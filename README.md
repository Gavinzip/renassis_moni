# Renaiss 真實市價即時監控系統 📈

這是一套針對 Renaiss 平台設計的 **「全實時、增量式」** 市場套利監控系統。透過整合 PriceCharting 與 SNKRDUNK 的即時大數據，協助你第一時間發現低於市價的撿漏機會。

---

## � 核心功能
- **全實時抓取**：每 1 分鐘對新上架物件發動 PC & SNKR 實時爬蟲。
- **增量監控**：自動追蹤已讀 ID，不重複處理舊掛單，節省 API 消耗。
- **雙來源比價**：獨立參考日美兩大市場，只要任一來源有利潤即刻報警。
- **30天平均**：自動計算最近 30 天內的歷史成交均價 (含等級匹配與離群值過濾)。

---

## �️ 快速啟動

### 1. 配置環境
建議使用 `.env` 檔案進行設定：
```bash
# 1. 複製設定範本
cp .env.example .env

# 2. 填入你的 Discord Webhook 與參數
# DISCORD_WEBHOOK_URL=你的網址
# PRICE_THRESHOLD=20.0 (價差門檻)
```

### 2. 安裝與執行
```bash
# 安裝相依套件
pip install -r requirements.txt

# 背景執行並輸出日誌
nohup python3 -u scripts/market_monitor.py > market_monitor.log 2>&1 &
```

---

## 🔔 警報說明
- **報警條件**：當系統計算出 `市場均價 - 賣家開價 >= $20 USD` (預設) 時觸發。
- **通知內容**：包含卡片名稱、等級、開價、兩大平台均價及跳轉連結。

### 查看運行日誌
```bash
tail -f market_monitor.log
```
只要日誌中出現 `🚨 [真正撿漏警報]`，就是進場買入的時機！

---

## 🛡️ 檔案結構
- `scripts/market_monitor.py`: 主程序，負責循環讀取與邏輯判斷。
- `scripts/market_report_vision.py`: 爬蟲引擎，負責各平台數據抓取。
- `SKILL.md`: 提供給 AI Agent 的標準技能規範文件。
- `.env.example`: 環境變數配置範本。
