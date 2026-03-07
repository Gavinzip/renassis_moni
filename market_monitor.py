import requests
import re
import json
import time
from datetime import datetime, timedelta
import os
import sys

# Import search functions locally
import market_report_vision as mrv

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
# 🆕 加入可條整參數
WINDOW_DAYS = int(os.getenv("WINDOW_DAYS", 30))
PRICE_THRESHOLD = float(os.getenv("PRICE_THRESHOLD", 30))

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


def run_monitor_cycle():
    items = fetch_market_data()
    if not items:
        return
        
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 成功抓取 {len(items)} 筆目前市場掛單，開始進行逐一實時查價...")
    
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


if __name__ == "__main__":
    print("啟動 Renaiss 極致「全實時」監控機器人 (現場抓取分析模式)...")
    print(f"⚙️  當前設定: 價差門檻=${PRICE_THRESHOLD} USD | 時間窗口={WINDOW_DAYS} 天")
    print(f"🔔  Discord 通知: {'已開啟' if DISCORD_WEBHOOK_URL else '未開啟 (請設定 DISCORD_WEBHOOK_URL)'}")
    
    while True:
        try:
            run_monitor_cycle()
        except Exception as e:
            print(f"Monitor Crash: {e}")

            
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 休眠 5 分鐘...")
        time.sleep(300)
