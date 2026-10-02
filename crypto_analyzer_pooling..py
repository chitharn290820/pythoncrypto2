"""
Crypto Momentum Analyzer
=========================
ดึงข้อมูลราคาเหรียญคริปโตจาก CoinGecko (ใช้ Demo API key ฟรี แนะนำสำหรับรันบน Render)
คำนวณอินดิเคเตอร์เชิงเทคนิคจากข้อมูลย้อนหลัง แล้วจัดอันดับเหรียญ
ที่มี "โมเมนตัมเชิงบวก" มากที่สุด พร้อมสร้างแดชบอร์ด HTML แบบสวยงาม

⚠️ ข้อควรรู้ก่อนใช้งาน (สำคัญมาก):
- ไม่มีโมเดลหรือสคริปต์ใดในโลกที่ "การันตีกำไร" ในการเทรดระยะสั้นได้จริง
  ราคาคริปโตผันผวนสูงและได้รับผลจากข่าว/สภาพคล่อง/แรงเทรดสถาบันที่คาดการณ์ล่วงหน้าไม่ได้
- สคริปต์นี้ให้ "คะแนนโมเมนตัมเชิงสถิติ" (RSI, MACD, MA cross, ผลตอบแทนย้อนหลัง,
  ความผันผวน, ปริมาณซื้อขาย) เพื่อช่วยประกอบการตัดสินใจเท่านั้น ไม่ใช่คำแนะนำการลงทุน
  และไม่ควรใช้เป็นสัญญาณซื้อขายเพียงอย่างเดียว
- ควรใช้ร่วมกับการบริหารความเสี่ยง (stop-loss, ขนาดโพซิชันที่เหมาะสม) เสมอ

หมายเหตุการแก้ไขจากเวอร์ชันก่อนหน้า:
1. CoinGecko public/free API เปลี่ยนนโยบาย: การระบุ `interval=daily` แบบ explicit
   ตอนนี้เป็นฟีเจอร์ของแผนเสียเงิน ถ้าขอช่วงยาว (เช่น 3 ปี) พร้อม interval=daily บน
   free tier มีโอกาสได้ข้อมูลผิดเพี้ยนหรือถูกตัด range -> เอาพารามิเตอร์ interval ออก
   แล้วปล่อยให้ API auto-select ความละเอียดเอง และลดค่าเริ่มต้นของ HISTORY_DAYS ลง
   เหลือ 365 วัน (free tier รองรับแน่นอน) ปรับเพิ่มได้ถ้า API ของคุณรองรับ
2. บั๊กจริงที่ทำให้ analyze_coin พังทุกเหรียญ: คอลัมน์ ts (timestamp มิลลิวินาที) ไม่เคย
   ถูกแปลงเป็น datetime index เลย ทำให้ตอนสร้าง history_dates ด้วย d.strftime(...)
   จะ error เพราะ index เป็นเลข ไม่ใช่ datetime -> แก้โดยแปลง ts เป็น datetime แล้ว
   set เป็น index ให้ df ตั้งแต่ตอนดึงข้อมูล
3. เพิ่ม debug print ใน analyze_coin ว่าเหรียญไหนถูกตัดออกเพราะข้อมูลไม่พอ จะได้เห็น
   สาเหตุชัดเจนแทนที่จะเงียบแล้วบอกแค่ "ไม่พบข้อมูลเพียงพอ" รวมๆ ท้ายสุด

วิธีใช้:
    pip install requests pandas numpy
    export COINGECKO_API_KEY=CG-xxxxxxxx   # (ไม่บังคับในเครื่อง แต่แนะนำบน Render)
    python crypto_analyzer_pooling.py

ผลลัพธ์: ไฟล์ crypto_dashboard.html ที่เปิดดูในเบราว์เซอร์ได้ทันที
"""

import os
import time
import json
import math
import sys
import argparse
from datetime import datetime, timezone

import requests
import pandas as pd
import numpy as np

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
TOP_N_COINS = 45          # จำนวนเหรียญ (ตาม market cap) ที่จะนำมาวิเคราะห์
HISTORY_DAYS = 365        # free/demo tier ของ CoinGecko รองรับช่วงนี้แน่นอน
MIN_ROWS_REQUIRED = 220   # ต้องมีข้อมูลอย่างน้อยเท่านี้ถึงจะคำนวณ MA200 ได้
REQUEST_DELAY = float(os.environ.get("REQUEST_DELAY", "2.5"))  # วินาที (~24 req/นาที ต่ำกว่าเพดาน 30/นาที)
TOP_RESULT = 5
TARGET_PROFIT_PCT = 5.0   # เป้ากำไร (%) ที่ใช้ประมาณจำนวนวัน ปรับได้ตามต้องการ

CACHE_DIR = os.environ.get("CACHE_DIR", "cache")
CACHE_TTL_SEC = int(os.environ.get("CACHE_TTL_SEC", str(6 * 3600)))  # ใช้แคชซ้ำได้ 6 ชม.

# Demo API key (ฟรี) จาก https://www.coingecko.com/en/api  -> ตั้งเป็น Environment Variable
# ชื่อ COINGECKO_API_KEY บน Render. มี key = โควตาผูกกับ key ไม่ใช่ IP ที่แชร์กับคนอื่น
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "").strip()
HEADERS = {"User-Agent": "Mozilla/5.0 (crypto-momentum-analyzer)"}
if COINGECKO_API_KEY:
    HEADERS["x-cg-demo-api-key"] = COINGECKO_API_KEY


def _cache_path(name):
    return os.path.join(CACHE_DIR, f"{name}.json")


def cache_load(name):
    path = _cache_path(name)
    try:
        if time.time() - os.path.getmtime(path) < CACHE_TTL_SEC:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except (OSError, ValueError):
        pass
    return None


def cache_save(name, data):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(name), "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def http_get_with_retry(url, params, retries=6, label=""):
    """GET พร้อม retry/backoff. โดน 429 -> เคารพ Retry-After แล้วรอ, ไม่ยอมแพ้ง่าย"""
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
        except requests.RequestException as e:
            print(f"  -> {label}: request error {e}, ลองใหม่...")
            time.sleep(5)
            continue

        if r.status_code == 200:
            return r
        if r.status_code in (429, 500, 502, 503, 504):
            try:
                wait = int(r.headers.get("Retry-After", ""))
            except ValueError:
                wait = min(20 * (attempt + 1), 90)
            print(f"  -> {label}: status {r.status_code}, รอ {wait}s (ครั้งที่ {attempt+1}/{retries})")
            time.sleep(wait)
            continue
        print(f"  -> {label}: error status {r.status_code} | {r.text[:150]}")
        return None
    print(f"  -> {label}: ลองครบ {retries} ครั้งแล้วยังไม่สำเร็จ")
    return None


def get_top_coins(n=TOP_N_COINS):
    """ดึงรายชื่อเหรียญ top N ตาม market cap (มี cache + retry)"""
    cached = cache_load(f"top_{n}")
    if cached:
        print("  -> get_top_coins: ใช้ข้อมูลจากแคช")
        return cached
    r = http_get_with_retry(
        f"{COINGECKO_BASE}/coins/markets",
        {"vs_currency": "usd", "order": "market_cap_desc", "per_page": n, "page": 1},
        label="get_top_coins",
    )
    if not r:
        return None
    data = r.json()
    cache_save(f"top_{n}", data)
    return data


def get_history(coin_id, days=HISTORY_DAYS, retries=6):
    """ดึงราคา/ปริมาณย้อนหลัง (daily) ของเหรียญหนึ่งตัว (มี cache + retry)

    หมายเหตุ: ไม่ส่ง interval=daily เพราะเป็นฟีเจอร์แผนเสียเงิน ปล่อยให้ API
    auto-select ความละเอียดตามช่วงวัน (>90 วัน = รายวัน)
    """
    data = cache_load(f"hist_{coin_id}_{days}")
    from_cache = data is not None
    if data is None:
        r = http_get_with_retry(
            f"{COINGECKO_BASE}/coins/{coin_id}/market_chart",
            {"vs_currency": "usd", "days": days},
            retries=retries,
            label=coin_id,
        )
        if not r:
            return None
        data = r.json()
        cache_save(f"hist_{coin_id}_{days}", data)

    prices = pd.DataFrame(data.get("prices", []), columns=["ts", "price"])
    volumes = pd.DataFrame(data.get("total_volumes", []), columns=["ts", "volume"])
    if prices.empty:
        print(f"  -> {coin_id}: status 200 แต่ prices ว่างเปล่า")
        return None

    df = prices.merge(volumes, on="ts", how="left")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("ts").sort_index()
    print(f"  -> {coin_id}: OK ได้ {len(df)} แถว" + (" (แคช)" if from_cache else ""))
    get_history.last_from_cache = from_cache
    return df


get_history.last_from_cache = False


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def estimate_days_to_profit(returns, target_pct=TARGET_PROFIT_PCT):
    """ประมาณ (ไม่ใช่พยากรณ์!) จำนวนวันที่อาจถึงเป้ากำไร ถ้าซื้อวันนี้ที่ราคาปัจจุบัน

    วิธีคิด: เอาค่าเฉลี่ยผลตอบแทนรายวันในอดีต (compound) มา extrapolate ไปข้างหน้า
    แบบเส้นตรง สมมติว่าอนาคตพฤติกรรมเหมือนอดีต ซึ่ง "ไม่เป็นความจริงเสมอไป"
    - ถ้าเทรนด์ย้อนหลังเป็นลบหรือทรงตัว (mean daily return <= 0) จะ return None
      เพราะประมาณวันไปข้างหน้าแบบมีความหมายไม่ได้
    - ตัวเลขนี้ไม่ใช่การรับประกันกำไร เป็นแค่การประมาณเชิงสถิติจากอดีตเท่านั้น
    """
    mean_daily = returns.mean()
    if mean_daily is None or math.isnan(mean_daily) or mean_daily <= 0:
        return None
    try:
        days = math.log(1 + target_pct / 100) / math.log(1 + mean_daily)
    except (ValueError, ZeroDivisionError):
        return None
    return round(days, 1) if days > 0 else None


def watch_price(coin_id, interval=30):
    """โหมด realtime (polling): ดึงราคาล่าสุดซ้ำทุก ๆ interval วินาที
    หมายเหตุ: CoinGecko free tier ไม่มี WebSocket จริง นี่คือการ poll ซ้ำๆ เท่านั้น
    กด Ctrl+C เพื่อหยุด
    """
    url = f"{COINGECKO_BASE}/simple/price"
    params = {"ids": coin_id, "vs_currencies": "usd", "include_24hr_change": "true"}
    print(f"กำลังติดตามราคา {coin_id} แบบ realtime (poll ทุก {interval} วินาที) กด Ctrl+C เพื่อหยุด\n")
    try:
        while True:
            try:
                r = requests.get(url, params=params, headers=HEADERS, timeout=15)
                if r.status_code == 200:
                    data = r.json().get(coin_id, {})
                    price = data.get("usd")
                    chg24h = data.get("usd_24h_change")
                    ts = datetime.now().strftime("%H:%M:%S")
                    chg_str = f"{chg24h:+.2f}%" if chg24h is not None else "-"
                    print(f"[{ts}] {coin_id}: ${price}  (24h: {chg_str})")
                else:
                    print(f"  -> error status {r.status_code}")
            except requests.RequestException as e:
                print(f"  -> request error: {e}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nหยุดการติดตามแล้ว")


def estimate_typical_hold_days(close, ma_window=50):
    """ข้อมูลอ้างอิงเชิงสถิติ (ไม่ใช่คำแนะนำ!): ดูย้อนหลังว่าตอนราคาอยู่เหนือ MA50
    (ช่วง "ขาขึ้น" ตามนิยามง่ายๆ) แต่ละรอบยาวนานกี่วันโดยเฉลี่ย/มัธยฐาน เพื่อใช้เป็น
    กรอบเวลาคร่าวๆ ประกอบการตัดสินใจของผู้ใช้เอง ไม่ใช่กฎตายตัวว่าต้องขายวันที่เท่าไหร่
    """
    ma = close.rolling(ma_window).mean()
    above = (close > ma).dropna()
    if above.empty:
        return None, None

    streaks = []
    current = 0
    for v in above:
        if v:
            current += 1
        else:
            if current > 0:
                streaks.append(current)
            current = 0
    if current > 0:
        streaks.append(current)

    if not streaks:
        return None, None

    avg_streak = sum(streaks) / len(streaks)
    streaks_sorted = sorted(streaks)
    mid = len(streaks_sorted) // 2
    median_streak = (streaks_sorted[mid] if len(streaks_sorted) % 2 == 1
                      else (streaks_sorted[mid - 1] + streaks_sorted[mid]) / 2)
    return round(avg_streak, 1), round(median_streak, 1)


def analyze_coin(coin_id, symbol, name, df):
    """คำนวณชุดอินดิเคเตอร์และให้คะแนนโมเมนตัม (0-100)"""
    close = df["price"].dropna()
    vol = df["volume"].dropna()

    if len(close) < MIN_ROWS_REQUIRED:
        print(f"  -> {symbol}: ข้ามเพราะมีข้อมูลแค่ {len(close)} แถว "
              f"(ต้องการอย่างน้อย {MIN_ROWS_REQUIRED})")
        return None

    returns = close.pct_change().dropna()

    r7 = (close.iloc[-1] / close.iloc[-8] - 1) * 100 if len(close) > 8 else np.nan
    r30 = (close.iloc[-1] / close.iloc[-31] - 1) * 100 if len(close) > 31 else np.nan
    r90 = (close.iloc[-1] / close.iloc[-91] - 1) * 100 if len(close) > 91 else np.nan
    r365 = (close.iloc[-1] / close.iloc[-366] - 1) * 100 if len(close) > 366 else np.nan

    ma50 = close.rolling(50).mean().iloc[-1]
    ma200 = close.rolling(200).mean().iloc[-1]
    golden_cross = bool(ma50 > ma200) if not (math.isnan(ma50) or math.isnan(ma200)) else False

    rsi_val = rsi(close).iloc[-1]
    macd_line, signal_line = macd(close)
    macd_bullish = bool(macd_line.iloc[-1] > signal_line.iloc[-1])

    vol_annualized = returns.std() * math.sqrt(365) * 100  # ความผันผวนต่อปี %
    sharpe_like = (returns.mean() * 365) / (returns.std() * math.sqrt(365) + 1e-9)

    vol_7d_avg = vol.iloc[-7:].mean()
    vol_30d_avg = vol.iloc[-30:].mean()
    volume_trend = ((vol_7d_avg / vol_30d_avg) - 1) * 100 if vol_30d_avg else 0

    est_days = estimate_days_to_profit(returns, TARGET_PROFIT_PCT)
    avg_hold_days, median_hold_days = estimate_typical_hold_days(close, ma_window=50)

    # --- คะแนนรวม (weighted, ปรับ weight ได้ตามต้องการ) ---
    def clip01(x, lo, hi):
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return 0.5
        return max(0.0, min(1.0, (x - lo) / (hi - lo)))

    score = (
        clip01(r7, -15, 15) * 20 +
        clip01(r30, -30, 30) * 15 +
        clip01(r90, -40, 40) * 10 +
        (15 if golden_cross else 0) +
        (15 if macd_bullish else 0) +
        clip01(50 - abs(rsi_val - 55), 0, 50) * 10 +   # RSI ใกล้โซน 50-65 (ขาขึ้นยังไม่ overbought)
        clip01(volume_trend, -20, 40) * 10 +
        clip01(sharpe_like, -1, 2) * 5
    )

    return {
        "id": coin_id,
        "symbol": symbol.upper(),
        "name": name,
        "price": float(close.iloc[-1]),
        "r7": round(r7, 2) if not math.isnan(r7) else None,
        "r30": round(r30, 2) if not math.isnan(r30) else None,
        "r90": round(r90, 2) if not math.isnan(r90) else None,
        "r365": round(r365, 2) if not math.isnan(r365) else None,
        "rsi": round(float(rsi_val), 1) if not math.isnan(rsi_val) else None,
        "golden_cross": golden_cross,
        "macd_bullish": macd_bullish,
        "volatility_annual_pct": round(vol_annualized, 1),
        "volume_trend_pct": round(volume_trend, 1),
        "sharpe_like": round(float(sharpe_like), 2),
        "score": round(float(score), 1),
        "target_profit_pct": TARGET_PROFIT_PCT,
        "est_days_to_profit": est_days,   # None ถ้าเทรนด์ย้อนหลังไม่เป็นบวก, ประมาณการเท่านั้น
        "avg_uptrend_days": avg_hold_days,       # ข้อมูลอ้างอิง: รอบขาขึ้นในอดีตยาวเฉลี่ยกี่วัน
        "median_uptrend_days": median_hold_days, # มัธยฐาน (กันค่า outlier ดึงค่าเฉลี่ยเพี้ยน)
        "history_dates": [d.strftime("%Y-%m-%d") for d in close.index[-180:]],
        "history_prices": [round(float(p), 6) for p in close.iloc[-180:]],
    }


def build_dashboard_html(results, out_path="crypto_dashboard.html"):
    top5 = sorted(results, key=lambda x: x["score"], reverse=True)[:TOP_RESULT]
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html = f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<title>Crypto Momentum Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.4/chart.umd.min.js"></script>
<style>
  :root {{
    --bg:#0d1117; --panel:#151b23; --panel2:#1c242e; --text:#e6edf3;
    --muted:#8b98a5; --accent:#3fb950; --accent2:#f0883e; --danger:#f85149; --line:#2a333d;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text); font-family:'Segoe UI',system-ui,sans-serif; }}
  header {{ padding:28px 32px 16px; border-bottom:1px solid var(--line); }}
  header h1 {{ margin:0 0 6px; font-size:1.6rem; letter-spacing:-0.02em; }}
  header p {{ margin:0; color:var(--muted); font-size:0.9rem; }}
  .warning {{ margin:16px 32px; padding:14px 18px; background:#3b1f14; border:1px solid #7a3b1e;
    border-radius:8px; color:#ffd6ae; font-size:0.85rem; line-height:1.5; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(340px,1fr)); gap:18px; padding:24px 32px 40px; }}
  .card {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:18px 20px; }}
  .card-head {{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:6px; }}
  .rank {{ font-size:0.75rem; color:var(--muted); }}
  .name {{ font-size:1.15rem; font-weight:600; }}
  .sym {{ color:var(--muted); font-size:0.85rem; margin-left:6px; }}
  .score {{ font-size:1.4rem; font-weight:700; color:var(--accent); }}
  .price {{ font-size:1.05rem; margin:4px 0 12px; color:var(--text); }}
  canvas {{ max-height:110px; margin-bottom:12px; }}
  .metrics {{ display:grid; grid-template-columns:1fr 1fr; gap:6px 14px; font-size:0.82rem; color:var(--muted); }}
  .metrics b {{ color:var(--text); }}
  .pos {{ color:var(--accent); }} .neg {{ color:var(--danger); }}
  table {{ width:calc(100% - 64px); margin:0 32px 40px; border-collapse:collapse; font-size:0.85rem; }}
  th, td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:right; }}
  th:first-child, td:first-child {{ text-align:left; }}
  th {{ color:var(--muted); font-weight:500; font-size:0.75rem; text-transform:uppercase; letter-spacing:.04em; }}
  footer {{ padding:20px 32px 40px; color:var(--muted); font-size:0.78rem; border-top:1px solid var(--line); }}
</style>
</head>
<body>
<header>
  <h1>Crypto Momentum Dashboard</h1>
  <p>วิเคราะห์จากข้อมูลราคาและปริมาณซื้อขายย้อนหลัง (CoinGecko) · อัปเดตล่าสุด {generated_at}</p>
</header>
<div class="warning">
  ⚠️ นี่คือคะแนนโมเมนตัมเชิงสถิติ ไม่ใช่การรับประกันกำไร การเทรดคริปโตระยะสั้นมีความเสี่ยงสูงมาก
  ราคาอาจเคลื่อนไหวสวนทางกับคะแนนได้เสมอ โปรดใช้ประกอบการตัดสินใจร่วมกับการบริหารความเสี่ยงของคุณเอง<br>
  ⚠️ ตัวเลข "ประมาณวันถึงเป้ากำไร {TARGET_PROFIT_PCT}%" คำนวณจากค่าเฉลี่ยผลตอบแทนย้อนหลังของแต่ละเหรียญ
  แบบ extrapolate ไปข้างหน้าเท่านั้น <b>ไม่ใช่การพยากรณ์ราคาจริง</b> ถ้าเทรนด์ย้อนหลังไม่เป็นบวก
  ระบบจะแสดงว่า "ประมาณไม่ได้" เพราะไม่มีความหมายทางสถิติที่จะยืด
</div>
<div class="grid" id="top5"></div>
<table id="fulltable">
  <thead><tr>
    <th>เหรียญ</th><th>ราคา (USD)</th><th>7 วัน</th><th>30 วัน</th><th>90 วัน</th>
    <th>RSI</th><th>Golden Cross</th><th>MACD</th><th>ความผันผวน/ปี</th><th>คะแนน</th>
    <th>ประมาณวันถึงกำไร {TARGET_PROFIT_PCT}%</th><th>รอบขาขึ้นในอดีต (มัธยฐาน)</th>
  </tr></thead>
  <tbody></tbody>
</table>
<footer>
  ข้อมูลจาก CoinGecko Public API · สคริปต์นี้จัดทำเพื่อการศึกษาเท่านั้น ไม่ใช่คำแนะนำทางการเงิน
</footer>
<script>
const top5 = {json.dumps(top5, ensure_ascii=False)};
const allResults = {json.dumps(sorted(results, key=lambda x: x["score"], reverse=True), ensure_ascii=False)};

const grid = document.getElementById('top5');
top5.forEach((c, i) => {{
  const card = document.createElement('div');
  card.className = 'card';
  const chg = (v) => v == null ? '-' : (v >= 0 ? '+' : '') + v + '%';
  const cls = (v) => v == null ? '' : (v >= 0 ? 'pos' : 'neg');
  card.innerHTML = `
    <div class="card-head">
      <div><span class="name">#${{i+1}} ${{c.name}}</span><span class="sym">${{c.symbol}}</span></div>
      <div class="score">${{c.score}}</div>
    </div>
    <div class="price">$${{c.price.toLocaleString(undefined,{{maximumFractionDigits: c.price < 1 ? 6 : 2}})}}</div>
    <canvas id="chart${{i}}"></canvas>
    <div class="metrics">
      <div>7 วัน: <b class="${{cls(c.r7)}}">${{chg(c.r7)}}</b></div>
      <div>30 วัน: <b class="${{cls(c.r30)}}">${{chg(c.r30)}}</b></div>
      <div>90 วัน: <b class="${{cls(c.r90)}}">${{chg(c.r90)}}</b></div>
      <div>RSI(14): <b>${{c.rsi ?? '-'}}</b></div>
      <div>Golden Cross: <b>${{c.golden_cross ? 'ใช่' : 'ไม่'}}</b></div>
      <div>MACD ขาขึ้น: <b>${{c.macd_bullish ? 'ใช่' : 'ไม่'}}</b></div>
      <div>ผันผวน/ปี: <b>${{c.volatility_annual_pct}}%</b></div>
      <div>เทรนด์ Volume: <b class="${{cls(c.volume_trend_pct)}}">${{chg(c.volume_trend_pct)}}</b></div>
      <div>ถึงกำไร ${{c.target_profit_pct}}%: <b>${{c.est_days_to_profit ? '~' + c.est_days_to_profit + ' วัน' : 'ประมาณไม่ได้'}}</b></div>
      <div>ขาขึ้นในอดีตยาวเฉลี่ย: <b>${{c.median_uptrend_days ? '~' + c.median_uptrend_days + ' วัน' : '-'}}</b></div>
    </div>`;
  grid.appendChild(card);
}});

top5.forEach((c, i) => {{
  new Chart(document.getElementById('chart'+i), {{
    type: 'line',
    data: {{ labels: c.history_dates, datasets: [{{
      data: c.history_prices, borderColor: '#3fb950', borderWidth: 1.5,
      pointRadius: 0, tension: 0.15, fill: false
    }}]}},
    options: {{
      responsive: true, maintainAspectRatio: true,
      plugins: {{ legend: {{ display:false }}, tooltip: {{ enabled:false }} }},
      scales: {{ x: {{ display:false }}, y: {{ display:false }} }}
    }}
  }});
}});

const tbody = document.querySelector('#fulltable tbody');
allResults.forEach(c => {{
  const tr = document.createElement('tr');
  const chg = (v) => v == null ? '-' : (v >= 0 ? '+' : '') + v + '%';
  tr.innerHTML = `<td>${{c.name}} <span style="color:var(--muted)">${{c.symbol}}</span></td>
    <td>$${{c.price.toLocaleString(undefined,{{maximumFractionDigits: c.price < 1 ? 6 : 2}})}}</td>
    <td>${{chg(c.r7)}}</td><td>${{chg(c.r30)}}</td><td>${{chg(c.r90)}}</td>
    <td>${{c.rsi ?? '-'}}</td><td>${{c.golden_cross ? '✓' : '—'}}</td><td>${{c.macd_bullish ? '✓' : '—'}}</td>
    <td>${{c.volatility_annual_pct}}%</td><td><b>${{c.score}}</b></td>
    <td>${{c.est_days_to_profit ? '~' + c.est_days_to_profit + ' วัน' : 'ประมาณไม่ได้'}}</td>
    <td>${{c.median_uptrend_days ? '~' + c.median_uptrend_days + ' วัน' : '-'}}</td>`;
  tbody.appendChild(tr);
}});
</script>
</body>
</html>"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"สร้างแดชบอร์ดเรียบร้อย: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Crypto Momentum Analyzer")
    parser.add_argument("--watch", metavar="COIN_ID",
                         help="ติดตามราคาเหรียญเดียวแบบ realtime (polling) เช่น --watch bitcoin")
    parser.add_argument("--interval", type=int, default=30,
                         help="วินาทีระหว่างการ poll ราคาในโหมด --watch (default 30)")
    args = parser.parse_args()

    if args.watch:
        watch_price(args.watch, interval=args.interval)
        return

    if not COINGECKO_API_KEY:
        print("⚠️ ไม่พบ COINGECKO_API_KEY (ใช้โหมดไม่มี key) บน Render มักโดน 429 "
              "แนะนำให้ตั้ง Demo API key ฟรีเป็น Environment Variable")
    print("กำลังดึงรายชื่อเหรียญ top", TOP_N_COINS, "...")
    coins = get_top_coins(TOP_N_COINS)

    if not coins:
        print("ดึงรายชื่อเหรียญไม่สำเร็จ (ดู error ด้านบน)")
        sys.exit(1)

    results = []
    for i, c in enumerate(coins):
        coin_id = c["id"]
        print(f"[{i+1}/{len(coins)}] ดึงข้อมูลย้อนหลังของ {c['symbol'].upper()} ...")
        df = get_history(coin_id)
        if df is not None:
            res = analyze_coin(coin_id, c["symbol"], c["name"], df)
            if res:
                results.append(res)
        if not get_history.last_from_cache:
            time.sleep(REQUEST_DELAY)  # กัน rate limit ของ CoinGecko

    if not results:
        print("\nไม่พบข้อมูลเพียงพอสำหรับการวิเคราะห์")
        print("ดูบรรทัด '-> ... ข้ามเพราะมีข้อมูลแค่ ... แถว' ด้านบนเพื่อหาสาเหตุ")
        sys.exit(1)

    results.sort(key=lambda x: x["score"], reverse=True)

    print("\n=== TOP 5 เหรียญที่มีคะแนนโมเมนตัมสูงสุด ===")
    for i, r in enumerate(results[:TOP_RESULT], 1):
        est = f"~{r['est_days_to_profit']} วัน" if r['est_days_to_profit'] else "ประมาณไม่ได้ (เทรนด์ไม่เป็นบวก)"
        hold = f"~{r['median_uptrend_days']} วัน" if r['median_uptrend_days'] else "ไม่มีข้อมูลย้อนหลังพอ"
        print(f"{i}. {r['name']} ({r['symbol']}) - คะแนน {r['score']} "
              f"| 7d {r['r7']}% | 30d {r['r30']}% | RSI {r['rsi']} "
              f"| ประมาณวันถึงกำไร {TARGET_PROFIT_PCT}%: {est} "
              f"| รอบขาขึ้นในอดีตยาวเฉลี่ย: {hold}")
    print("\n⚠️ ตัวเลข 'ประมาณวันถึงกำไร' เป็นการ extrapolate จากค่าเฉลี่ยผลตอบแทนย้อนหลังเท่านั้น "
          "ไม่ใช่การพยากรณ์ราคาจริงและไม่รับประกันผลลัพธ์")
    print("⚠️ 'รอบขาขึ้นในอดีตยาวเฉลี่ย' เป็นแค่สถิติว่าที่ผ่านมารอบขาขึ้นของเหรียญนี้ยาวแค่ไหน "
          "ไม่ใช่คำแนะนำว่าควรถือกี่วัน อนาคตอาจสั้นหรือยาวกว่านี้มากก็ได้ — ควรใช้ stop-loss/"
          "เป้าหมายกำไรของตัวเองประกอบเสมอ")

    with open("crypto_analysis_full.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    build_dashboard_html(results)


if __name__ == "__main__":
    main()
