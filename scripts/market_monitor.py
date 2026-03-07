import requests
import re
import json
import time
from datetime import datetime, timedelta
import os
import sys

# Import search functions locally
import market_report_vision as mrv
from dotenv import load_dotenv

# 📜 載入 .env 檔案 (推薦)
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path)

# 📝 手動設定區 (若不使用 .env，請直接在此修改引號內的內容)
# ---------------------------------------------------------
DEFAULT_DISCORD_WEBHOOK = ""  # 在此填入 Webhook 網址
DEFAULT_WINDOW_DAYS = 30                        # 價格計算窗口 (天)
DEFAULT_PRICE_THRESHOLD = 20.0                  # 報警價差門檻 (USD)
# ---------------------------------------------------------

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL") or DEFAULT_DISCORD_WEBHOOK
WINDOW_DAYS = int(os.getenv("WINDOW_DAYS") or DEFAULT_WINDOW_DAYS)
PRICE_THRESHOLD = float(os.getenv("PRICE_THRESHOLD") or DEFAULT_PRICE_THRESHOLD)

# 📦 狀態管理：追蹤已處理過的掛單 ID
SEEN_IDS_FILE = os.path.join(os.path.dirname(__file__), "seen_ids.txt")
SEEN_IDS = set()

def load_seen_ids():
    """從檔案載入已見過的 ID"""
    if os.path.exists(SEEN_IDS_FILE):
        try:
            with open(SEEN_IDS_FILE, "r") as f:
                return set(line.strip() for line in f if line.strip())
        except Exception as e:
            print(f"⚠️ 載入 seen_ids.txt 失敗: {e}")
    return set()

def save_seen_id(item_id):
    """將單一 ID 追加到檔案中"""
    try:
        with open(SEEN_IDS_FILE, "a") as f:
            f.write(f"{item_id}\n")
    except Exception as e:
        print(f"⚠️ 儲存 seen_ids 失敗: {e}")

def parse_date_string(date_str):
    """解析 PC 和 SNKR 的各種日期格式，返回 datetime 對象"""
    now = datetime.now()
    date_str = date_str.strip()
    
    # 1. 處理 YYYY-MM-DD (PC or SNKR)
    try:
        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
            return datetime.strptime(date_str, '%Y-%m-%d')
        if re.match(r'^\d{4}/\d{2}/\d{2}$', date_str):
            return datetime.strptime(date_str, '%Y/%m/%d')
    except: pass
    
    # 2. 處理 Mar 8, 2024 (PC)
    try:
        if re.match(r'^[A-Z][a-z]{2}\s\d{1,2},\s\d{4}$', date_str):
            return datetime.strptime(date_str, '%b %d, %Y')
    except: pass
    
    # 3. 處理相對時間 (SNKRJP: 5 分前, 2 時間前, 3 日前)
    m = re.match(r'^(\d+)\s*(分|時間|日)前$', date_str)
    if m:
        val = int(m.group(1))
        unit = m.group(2)
        if unit == '分': return now - timedelta(minutes=val)
        if unit == '時間': return now - timedelta(hours=val)
        if unit == '日': return now - timedelta(days=val)

    # 4. 處理相對時間 (SNKREN: 5 minutes ago, 2 hours ago, 3 days ago)
    m = re.search(r'(\d+)\s+(minute|hour|day)', date_str, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        unit = m.group(2).lower()
        if unit == 'minute': return now - timedelta(minutes=val)
        if unit == 'hour': return now - timedelta(hours=val)
        if unit == 'day': return now - timedelta(days=val)
        
    return None

def calculate_source_average(records, target_grade, window_days=30):
    """計算特定來源在指定天數內的平均價（含等級匹配與誤差過濾）"""
    if not records:
        return None, 0
    
    now = datetime.now()
    all_prices = []
    
    # 匹配等級（考慮 Unknown -> Ungraded）
    snkr_target = target_grade.replace(" ", "")
    
    for r in records:
        r_grade = r.get('grade', '')
        # 建立匹配邏輯
        matched = False
        if r_grade == target_grade:
            matched = True
        elif target_grade == "Unknown" and r_grade in ("Ungraded", "裸卡", "A"):
            matched = True
        elif r_grade == snkr_target:
            matched = True
            
        if not matched:
            continue
            
        # 檢查日期窗口
        d_str = r.get('date', '')
        d_obj = parse_date_string(d_str)
        if d_obj:
            if now - d_obj > timedelta(days=window_days):
                continue
        elif d_str: # 如果有日期但解析失敗，預設保留（或可選擇略過）
            pass
            
        # 提取價格
        p = r.get('price')
        if p and p > 0:
            all_prices.append(float(p))
            
    if not all_prices:
        return None, 0
        
    # IQR 過濾離群值 (至少 4 筆才過濾)
    if len(all_prices) >= 4:
        s_prices = sorted(all_prices)
        n = len(s_prices)
        q1 = s_prices[n // 4]
        q3 = s_prices[(n * 3) // 4]
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        filtered = [p for p in s_prices if lower <= p <= upper]
        prices_to_use = filtered if filtered else s_prices
    else:
        prices_to_use = all_prices
        
    avg = sum(prices_to_use) / len(prices_to_use)
    return avg, len(all_prices)
def calculate_true_average_with_window(pc_records, snkr_records, target_grade):
    """(兼容舊版或輔助調用) 使用全局設定的天數計算均價"""
    pc_avg, pc_count = calculate_source_average(pc_records, target_grade, window_days=WINDOW_DAYS)
    snkr_avg, snkr_count = calculate_source_average(snkr_records, target_grade, window_days=WINDOW_DAYS)
    return (pc_avg, pc_count), (snkr_avg, snkr_count)
def parse_renaiss_name(full_name):
    grade_m = re.search(r'(PSA|BGS|CGC|SGC)\s+(\d+(?:\.\d+)?)', full_name)
    grade_tag = f"{grade_m.group(1)} {grade_m.group(2)}" if grade_m else "Unknown"

    # Clean variant keywords from name for better searching
    variant_kws = ["FOIL", "SP", "ALT ART", "Parallel", "WANTED", "Leader", "SEC", "SR", "R", "UC", "C", "L", "Special Card"]
    
    # OP/ST pattern: OP01-001 or ST04-005 or OP01 001
    op_m = re.search(r'([A-Z0-9]{2,}\d[A-Z]?)[-\s](\d+)', full_name)
    if op_m:
        set_code = op_m.group(1)
        number = op_m.group(2)
        clean_name = full_name.replace(op_m.group(0), "").strip()
        if grade_m:
            clean_name = clean_name.replace(grade_m.group(0), "").strip()
        
        # Further clean name
        for kw in variant_kws:
            clean_name = re.sub(rf'\b{re.escape(kw)}\b', '', clean_name, flags=re.IGNORECASE).strip()
            
        return clean_name, number, set_code.upper(), grade_tag

    m = re.search(r'#([-A-Za-z0-9]+)', full_name)
    if not m:
        m = re.search(r'\s+([A-Z0-9]{2,}/\d+)$', full_name)
        if not m:
            clean_name = full_name
            if grade_m:
                clean_name = clean_name.replace(grade_m.group(0), "").strip()
            for kw in variant_kws:
                clean_name = re.sub(rf'\b{re.escape(kw)}\b', '', clean_name, flags=re.IGNORECASE).strip()
            return clean_name, "0", "", grade_tag

    number = m.group(1)
    clean_name = full_name.replace(f"#{number}", "").strip()
    if grade_m:
        clean_name = clean_name.replace(grade_m.group(0), "").strip()
    for kw in variant_kws:
        clean_name = re.sub(rf'\b{re.escape(kw)}\b', '', clean_name, flags=re.IGNORECASE).strip()

    sc_m = re.search(r'([A-Za-z0-9]{2,}\d[A-Za-z]?)-', full_name)
    set_code = sc_m.group(1) if sc_m else ""

    return clean_name, number, set_code, grade_tag


def clean_price(v):
    if not v or v == "NO-OFFER-PRICE": return None
    v = v.replace("$n", "")
    if len(v) > 10:
        return float(v) / (10**18)
    return float(v) / 100

def fetch_market_data():
    url = "https://www.renaiss.xyz/marketplace"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        pattern = r'\{\\"id\\":\\"[^"]+\\",\\"tokenId\\":\\"[^"]+\\",\\"itemId\\":\\"[^"]+\\",\\"name\\":\\".*?\\"buybackBaseValueInUSD\\":\\".*?\\"\}'
        matches = re.findall(pattern, resp.text)
        
        parsed_items = []
        for m in matches:
            try:
                data = json.loads(m.encode().decode('unicode_escape'))
                parsed_items.append({
                    "id": data.get("id"),
                    "item_id": data.get("itemId"),
                    "name": data.get("name"),
                    "ask_price": clean_price(data.get("askPriceInUSDT")),
                    "fmv": clean_price(data.get("fmvPriceInUSD")),
                    "grade": f"{data.get('gradingCompany')} {data.get('grade')}"
                })
            except: pass
        return parsed_items
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 網路請求失敗: {e}")
        return []

def fetch_and_analyze_realtime(item_id, full_name, grading_company, year):
    """現場發動爬蟲並分析價格 (分開回傳 PC 與 SNKR 的數據)"""
    print(f"  🔍 正在對 {full_name} 進行實時市場分析...")
    card_name, number, set_code, grade_tag = parse_renaiss_name(full_name)
    
    # 類別偵測
    category = "Pokemon"
    if any(kw in full_name or kw in (set_code or "") for kw in ["One Piece", "OP0", "ST0", "EB0", "WANTED", "Parallel", "Alt-Art"]):
        category = "One Piece"
    
    is_jp = "Japanese" in full_name
    
    # 變體偵測
    variant_map = {
        "manga": ["コミパラ", "manga"],
        "parallel": ["パラレル"],
        "wanted": ["wanted"],
        "-sp": ["sp", "-sp"],
        "l-p": ["l-p"],
        "sr-p": ["sr-p"],
        "flagship": ["flagship", "フラッグシップ", "フラシ"]
    }
    snkr_variants = []
    name_lower = full_name.lower()
    for category_kw, kws in variant_map.items():
        if any(kw in name_lower for kw in kws):
            snkr_variants.append(kws[0])
            
    is_alt_art = len(snkr_variants) > 0 or any(x in name_lower for x in ["special card", "alt art", "alternative"])
    
    # 執行 PC 搜尋與計算
    pc_records, pc_url, _ = mrv.search_pricecharting(
        name=card_name, number=number, set_code=set_code,
        target_grade=grade_tag, is_alt_art=is_alt_art, category=category
    )
    pc_avg, pc_count = calculate_source_average(pc_records, grade_tag, window_days=WINDOW_DAYS)
    
    # 執行 SNKR 搜尋與計算
    snkr_records, _, snkr_url = mrv.search_snkrdunk(
        en_name=card_name, jp_name="", number=number, set_code=set_code,
        target_grade=grade_tag, is_alt_art=is_alt_art, card_language="JP" if is_jp else "EN",
        snkr_variant_kws=snkr_variants
    )
    snkr_avg, snkr_count = calculate_source_average(snkr_records, grade_tag, window_days=WINDOW_DAYS)
    
    return (pc_avg, pc_count, pc_url), (snkr_avg, snkr_count, snkr_url)


def send_discord_alert(full_name, ask, pc_info, snkr_info):
    """發送 Discord Webhook 通知 (含雙來源詳細數據)"""
    if not DISCORD_WEBHOOK_URL:
        return
    
    pc_avg, pc_count, pc_url = pc_info
    snkr_avg, snkr_count, snkr_url = snkr_info

    fields = [
        {"name": "卡片名稱", "value": full_name, "inline": False},
        {"name": "賣家開價", "value": f"${ask:.2f} USD", "inline": True},
    ]
    
    if pc_avg:
        fields.append({"name": "PC 30天均價", "value": f"${pc_avg:.2f} USD ({pc_count}筆)", "inline": True})
    if snkr_avg:
        fields.append({"name": "SNKR 30天均價", "value": f"${snkr_avg:.2f} USD ({snkr_count}筆)", "inline": True})

    payload = {
        "content": f"🚨 **[真正撿漏警報]** {full_name}",
        "embeds": [
            {
                "title": f"發現套利機會！(觸發門檻: ${PRICE_THRESHOLD})",
                "color": 16711680,  # Red
                "fields": fields,
                "description": f"[🔗 PriceCharting]({pc_url or 'https://www.pricecharting.com'})\n[🔗 SNKRDUNK]({snkr_url or 'https://snkrdunk.com'})"
            }
        ]
    }
    
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        print(f"  ⚠️ Discord Webhook failed: {e}")

# LEGACY: background_idle_update removed for real-time focus


def run_monitor_cycle(limit=None, force_process=False):
    """
    監控循環：
    - limit: 限制處理筆數 (用於啟動測試)
    - force_process: 是否忽略 SEEN_IDS 檢查 (用於啟動測試)
    """
    items = fetch_market_data()
    if not items:
        return
        
    if limit:
        items = items[:limit]
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🧪 測試模式：僅檢查前 {limit} 筆掛單...")
    
    # 過濾已見過的 ID (除非強制處理)
    if not force_process:
        new_items = [it for it in items if it['item_id'] not in SEEN_IDS]
        if not new_items:
            return # 沒有新品，直接結束
        items = new_items
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ✨ 發現 {len(items)} 筆新品上架，開始查價...")
    else:
        if not limit:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 成功抓取 {len(items)} 筆掛單進行完全查價...")
    
    for item in items:
        item_id = item['item_id']
        ask = item['ask_price']
        full_name = item['name']
        
        # 1. 直接發動實時爬蟲
        company = full_name.split()[0] if "PSA" in full_name or "BGS" in full_name else "Unknown"
        year_match = re.search(r'20\d{2}', full_name)
        year = year_match.group(0) if year_match else 0
        
        pc_res, snkr_res = fetch_and_analyze_realtime(item_id, full_name, company, year)
        pc_avg, pc_count, pc_url = pc_res
        snkr_avg, snkr_count, snkr_url = snkr_res
        
        # 2. 獨立判斷折扣 (只要其中一個來源符合就報警)
        alert_pc = (pc_avg and (pc_avg - ask) >= PRICE_THRESHOLD)
        alert_snkr = (snkr_avg and (snkr_avg - ask) >= PRICE_THRESHOLD)
        
        # 日誌輸出
        log_parts = []
        if pc_avg: log_parts.append(f"PC({WINDOW_DAYS}d): ${pc_avg:.2f}")
        if snkr_avg: log_parts.append(f"SNKR({WINDOW_DAYS}d): ${snkr_avg:.2f}")
        print(f"  [掃描中] {full_name} | Ask: ${ask:.2f} | {' / '.join(log_parts) if log_parts else f'無{WINDOW_DAYS}天內數據'}")

        if alert_pc or alert_snkr:
            triggered_by = []
            if alert_pc: triggered_by.append(f"PC(${(pc_avg-ask):.2f})")
            if alert_snkr: triggered_by.append(f"SNKR(${(snkr_avg-ask):.2f})")
            
            print(f"\n🚨 [真正撿漏警報] {full_name}")
            print(f"   => 賣家開價: ${ask:.2f} USD")
            print(f"   🔥 觸發來源: {' & '.join(triggered_by)}！(門檻: ${PRICE_THRESHOLD}, 窗口: {WINDOW_DAYS}天) 請立刻注意把這張卡買下來！\n")
            
            # 發送 Discord Webhook
            send_discord_alert(full_name, ask, pc_res, snkr_res)
        
        # 標記為已見過並持久化
        if item_id not in SEEN_IDS:
            SEEN_IDS.add(item_id)
            save_seen_id(item_id)


if __name__ == "__main__":
    print("啟動 Renaiss 極致「全實時」監控機器人 (現場抓取分析模式)...")
    print(f"⚙️  當前設定: 價差門檻=${PRICE_THRESHOLD} USD | 時間窗口={WINDOW_DAYS} 天")
    print(f"🔔  Discord 通知: {'已開啟' if DISCORD_WEBHOOK_URL else '未開啟 (請設定 DISCORD_WEBHOOK_URL)'}")
    
    # 💥 初始狀態初始化：載入持久化數據 + 同步目前市場掛單
    print("📡 正在初始化市場狀態...")
    SEEN_IDS = load_seen_ids()
    print(f"📂 已從檔案載入 {len(SEEN_IDS)} 筆歷史記錄")
    
    try:
        initial_items = fetch_market_data()
        new_count = 0
        for it in initial_items:
            iid = it['item_id']
            if iid not in SEEN_IDS:
                SEEN_IDS.add(iid)
                save_seen_id(iid)
                new_count += 1
        print(f"✅ 已同步目前市場 {len(initial_items)} 筆掛單 (新增 {new_count} 筆至持久化)")
    except Exception as e:
        print(f"Initialization Failed: {e}")

    # 🚀 初次啟動：強行針對前 5 筆進行實時分析測試
    try:
        run_monitor_cycle(limit=5, force_process=True)
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🏁 啟動測試完成，5 秒後進入 1 分鐘循環監控...", flush=True)
        time.sleep(5)
    except Exception as e:
        print(f"Startup Test Failed: {e}", flush=True)

    while True:
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔃 正在掃描市場新掛單...", flush=True)
            run_monitor_cycle()
        except Exception as e:
            print(f"Monitor Crash: {e}", flush=True)

            
        time.sleep(60)
