"""
Web wrapper สำหรับ Render (Web Service)
- เปิดพอร์ตตาม $PORT เพื่อให้ Render ผ่านการตรวจ port
- รัน crypto_analyzer_pooling.main() ใน background thread (ตอนเริ่ม + เมื่อข้อมูลเก่าเกิน REFRESH_HOURS
  และมีคนเปิดเว็บ) แล้วเสิร์ฟ crypto_dashboard.html ที่ "/"
Start Command:  python server.py
"""
import os
import sys
import time
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import crypto_analyzer_pooling as analyzer

PORT = int(os.environ.get("PORT", "10000"))
REFRESH_HOURS = float(os.environ.get("REFRESH_HOURS", "6"))
DASHBOARD = "crypto_dashboard.html"

_lock = threading.Lock()
_running = False
_last_error = ""


def _run_analysis():
    global _running, _last_error
    try:
        sys.argv = ["crypto_analyzer_pooling.py"]  # กัน argparse อ่าน args ของ server
        analyzer.main()
        _last_error = ""
    except SystemExit:
        _last_error = "ดึงข้อมูลไม่สำเร็จ (ดู log) จะลองใหม่เมื่อมีคนเปิดหน้านี้อีกครั้ง"
    except Exception:
        _last_error = traceback.format_exc()[-500:]
        print(_last_error)
    finally:
        with _lock:
            _running = False


def ensure_fresh():
    """เริ่มวิเคราะห์ใหม่ถ้าไม่มีไฟล์/ไฟล์เก่า และยังไม่มีงานรันอยู่"""
    global _running
    with _lock:
        if _running:
            return
        stale = (not os.path.exists(DASHBOARD)
                 or time.time() - os.path.getmtime(DASHBOARD) > REFRESH_HOURS * 3600)
        if not stale:
            return
        _running = True
    threading.Thread(target=_run_analysis, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, "ok", "text/plain")
        ensure_fresh()
        if os.path.exists(DASHBOARD):
            with open(DASHBOARD, "rb") as f:
                return self._send(200, f.read())
        msg = _last_error or "กำลังดึงข้อมูลและวิเคราะห์ ใช้เวลาประมาณ 2-4 นาที หน้านี้จะรีเฟรชเอง..."
        self._send(200, f'<meta charset="utf-8"><meta http-equiv="refresh" content="20">'
                        f'<body style="font-family:sans-serif;padding:2rem"><h3>{msg}</h3></body>')

    def do_HEAD(self):
        self._send(200, "")

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    ensure_fresh()
    print(f"server listening on 0.0.0.0:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
