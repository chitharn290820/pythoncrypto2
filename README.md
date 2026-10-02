# Crypto Momentum Analyzer

## รันในเครื่อง
    pip install -r requirements.txt
    export COINGECKO_API_KEY=CG-xxxx      # ไม่บังคับในเครื่อง
    python crypto_analyzer_pooling.py     # สร้าง crypto_dashboard.html
    python server.py                      # หรือเปิดเป็นเว็บที่ http://localhost:10000

## Deploy บน Render
1. push ไฟล์ทั้งหมดขึ้น repo
2. New > Web Service (หรือ Blueprint เพื่อใช้ render.yaml)
3. Build: `pip install -r requirements.txt`  Start: `python server.py`
4. Environment: `COINGECKO_API_KEY` (Demo key ฟรีจาก coingecko.com/en/api)

## ตัวแปรที่ปรับได้
COINGECKO_API_KEY, REQUEST_DELAY (2.5), REFRESH_HOURS (6), CACHE_TTL_SEC (21600), CACHE_DIR (cache)
