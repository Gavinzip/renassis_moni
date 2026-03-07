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

# Rename the parse function so it can be used standalone or from scrape_all_cards_db
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

def calculate_true_average(pc_records, snkr_records, target_grade):
    """從即時抓取的紀錄中計算該等級的歷史均價."""
    all_prices = []
    
    # Process PC records
    pc_matched = [r for r in (pc_records or []) if r.get('grade') == target_grade]
    if not pc_matched and target_grade == "Unknown":
        pc_matched = [r for r in (pc_records or []) if r.get('grade') == "Ungraded"]
    
    for r in pc_matched:
        if r.get('price') and r['price'] > 0:
            all_prices.append(float(r['price']))
            
    # Process SNKR records
    snkr_target = target_grade.replace(" ", "")
    snkr_matched = [r for r in (snkr_records or []) if r.get('grade') in (target_grade, snkr_target)]
    if not snkr_matched and target_grade == "Unknown":
        snkr_matched = snkr_records or []
        
    for r in snkr_matched:
        if r.get('price') and r['price'] > 0:
            all_prices.append(float(r['price']))
            
    if not all_prices:
        return None, 0
        
    # Apply IQR filter
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


def fetch_and_analyze_realtime(item_id, full_name, grading_company, year):
    """現場發動爬蟲並分析價格"""
    print(f"  🔍 正在對 {full_name} 進行實時市場分析...")
    card_name, number, set_code, grade_tag = parse_renaiss_name(full_name)
    
    # Category Detection
    category = "Pokemon"
    if any(kw in full_name or kw in (set_code or "") for kw in ["One Piece", "OP0", "ST0", "EB0", "WANTED", "Parallel", "Alt-Art"]):
        category = "One Piece"
    
    is_jp = "Japanese" in full_name
    
    # Detect Variant Keywords
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
    
    # Perform Search
    pc_records, pc_url, _ = mrv.search_pricecharting(
        name=card_name, number=number, set_code=set_code,
        target_grade=grade_tag, is_alt_art=is_alt_art, category=category
    )
    snkr_records, _, snkr_url = mrv.search_snkrdunk(
        en_name=card_name, jp_name="", number=number, set_code=set_code,
        target_grade=grade_tag, is_alt_art=is_alt_art, card_language="JP" if is_jp else "EN",
        snkr_variant_kws=snkr_variants
    )
    
    # Calculate Real-Time Average
    true_avg, history_count = calculate_true_average(pc_records, snkr_records, grade_tag)
    
    return true_avg, history_count


def send_discord_alert(full_name, ask, avg, discount, history_count, pc_url, snkr_url):
    """發送 Discord Webhook 通知"""
    if not DISCORD_WEBHOOK_URL:
        return

    payload = {
        "content": f"🚨 **[真正撿漏警報]** {full_name}",
        "embeds": [
            {
                "title": f"撿漏機會：便宜了 {discount:.1f}%！",
                "color": 16711680,  # Red
                "fields": [
                    {"name": "卡片名稱", "value": full_name, "inline": False},
                    {"name": "賣家開價", "value": f"${ask:.2f} USD", "inline": True},
                    {"name": "市場均價", "value": f"${avg:.2f} USD", "inline": True},
                    {"name": "成交紀錄數", "value": f"{history_count} 筆", "inline": True}
                ],
                "description": f"[🔗 PriceCharting]({pc_url})\n[🔗 SNKRDUNK]({snkr_url})"
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
        grade = item['grade']
        
        # 1. 直接發動實時爬蟲 (不查資料庫舊價)
        company = full_name.split()[0] if "PSA" in full_name or "BGS" in full_name else "Unknown"
        year_match = re.search(r'20\d{2}', full_name)
        year = year_match.group(0) if year_match else 0
        
        true_avg, history_count = fetch_and_analyze_realtime(item_id, full_name, company, year)
        
        # 2. 現場判斷折扣
        if ask and true_avg and true_avg > 0 and history_count >= 1:
            discount_pct = (1.0 - (ask / true_avg)) * 100
            
            print(f"  [掃描中] {full_name} | Ask: ${ask:.2f} | Avg: ${true_avg:.2f} ({history_count}筆)")
            
            price_diff = true_avg - ask
            if price_diff >= 30:
                print(f"\n🚨 [真正撿漏警報] {full_name}")
                print(f"   => 賣家開價: ${ask:.2f} USD")
                print(f"   => 實時市場均價: ${true_avg:.2f} USD (來自 {history_count} 筆歷史成交)")
                print(f"   🔥 價差利潤: 便宜了 ${price_diff:.2f} USD！(門檻: $30) 請立刻注意把這張卡買下來！\n")
                
                # 發送 Discord Webhook
                send_discord_alert(full_name, ask, true_avg, discount_pct, history_count, 
                                   item.get('pc_url', 'https://www.pricecharting.com'), 
                                   item.get('snkr_url', 'https://snkrdunk.com'))
        elif ask:
             print(f"  [無數據] {full_name} | Ask: ${ask:.2f} | 無市場成交紀錄")


if __name__ == "__main__":
    print("啟動 Renaiss 極致「全實時」監控機器人 (現場抓取分析模式)...")
    
    while True:
        try:
            run_monitor_cycle()
        except Exception as e:
            print(f"Monitor Crash: {e}")

            
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 休眠 5 分鐘...")
        time.sleep(300)
