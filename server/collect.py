# -*- coding: utf-8 -*-
"""SomaPerf 采集服务：FastAPI + SQLite，单机轻量部署。"""
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("SOMA_DB", str(BASE_DIR / "soma_perf.db")))
IP_SALT = os.environ.get("SOMA_IP_SALT", "soma-perf-change-me")
SITE_TOKEN = os.environ.get("SOMA_SITE_TOKEN", "")
MAX_BODY_BYTES = 256 * 1024

UA_BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|headless|phantom|curl|wget|python|java-|node|scrapy",
    re.I,
)

_rate: dict = {}
_rate_lock = threading.Lock()


def log_msg(msg: str) -> None:
    """输出到 stdout，systemd 会捕获到 journalctl。"""
    print(f"[soma-perf] {msg}", flush=True)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id TEXT,
                event_type TEXT,
                ts INTEGER,
                received_at INTEGER,
                visitor_id TEXT,
                session_id TEXT,
                page TEXT,
                referrer TEXT,
                ua TEXT,
                device TEXT,
                os TEXT,
                browser TEXT,
                is_wechat INTEGER,
                ua_bot INTEGER,
                viewport TEXT,
                lang TEXT,
                ip_hash TEXT,
                bot_score INTEGER,
                is_bot INTEGER,
                payload_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events (event_type, ts);
            CREATE INDEX IF NOT EXISTS idx_events_visitor ON events (visitor_id);
            CREATE INDEX IF NOT EXISTS idx_events_page_ts ON events (page, ts);
            """
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="SomaPerf", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    xri = request.headers.get("x-real-ip", "")
    if xri:
        return xri.strip()
    return request.client.host if request.client else ""


def hash_ip(ip: str) -> str:
    if not ip:
        return ""
    return hashlib.sha256((ip + IP_SALT).encode("utf-8")).hexdigest()[:32]


def compute_bot_score(ev: dict) -> int:
    """0=机器人，100=真人；基于 UA 与服务端能看到的客户端特征。"""
    score = 50
    ua = ev.get("ua", "") or ""
    if UA_BOT_RE.search(ua):
        score -= 40
    if ev.get("uaBot"):
        score -= 20
    hints = ev.get("botHints") or {}
    if hints.get("webdriver"):
        score -= 40
    if hints.get("languages") == 0:
        score -= 15
    if hints.get("plugins") == 0 and ev.get("os") not in ("ios", "android"):
        score -= 5
    return max(0, min(100, score))


def rate_limited(ip: str, limit: int = 120, window: int = 60) -> bool:
    """简单内存滑动窗口限流：同一 IP 每分钟最多 limit 条事件。"""
    if not ip:
        return False
    now = time.time()
    with _rate_lock:
        if len(_rate) > 10000:
            _rate.clear()
        recent = [t for t in _rate.get(ip, []) if t > now - window]
        if len(recent) >= limit:
            _rate[ip] = recent
            return True
        recent.append(now)
        _rate[ip] = recent
    return False


def save_events(events: list, ip: str) -> int:
    ip_hash = hash_ip(ip)
    now = int(__import__("time").time() * 1000)
    conn = connect()
    try:
        cur = conn.cursor()
        for ev in events:
            bot_score = compute_bot_score(ev)
            cur.execute(
                """
                INSERT INTO events (
                    site_id, event_type, ts, received_at, visitor_id, session_id,
                    page, referrer, ua, device, os, browser, is_wechat, ua_bot,
                    viewport, lang, ip_hash, bot_score, is_bot, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ev.get("siteId", "default"),
                    ev.get("type", "unknown"),
                    int(ev.get("ts") or now),
                    now,
                    ev.get("visitorId"),
                    ev.get("sessionId"),
                    ev.get("page"),
                    ev.get("referrer"),
                    ev.get("ua"),
                    ev.get("device"),
                    ev.get("os"),
                    ev.get("browser"),
                    1 if ev.get("isWechat") else 0,
                    1 if ev.get("uaBot") else 0,
                    ev.get("viewport"),
                    ev.get("lang"),
                    ip_hash,
                    bot_score,
                    1 if bot_score <= 30 else 0,
                    json.dumps(ev, ensure_ascii=False, default=str)[:4000],
                ),
            )
        conn.commit()
        return len(events)
    finally:
        conn.close()


async def ingest(payload, request: Request):
    events = payload if isinstance(payload, list) else [payload]
    if not events:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)
    ip = client_ip(request)
    if rate_limited(ip):
        log_msg(f"rate limited ip={ip}")
        return JSONResponse({"ok": False, "error": "rate limited"}, status_code=429)
    if SITE_TOKEN:
        token = events[0].get("token") if isinstance(events[0], dict) else None
        if token != SITE_TOKEN:
            log_msg(f"forbidden ip={ip}")
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
    n = save_events(events, client_ip(request))
    log_msg(f"ingested {n} events from {ip}")
    return JSONResponse({"ok": True, "received": n})


@app.post("/collect")
async def collect(request: Request):
    try:
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            return JSONResponse({"ok": False, "error": "payload too large"}, status_code=413)
        payload = json.loads(body)
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)
    return await ingest(payload, request)


@app.get("/collect")
async def collect_get(data: str = "", request: Request = None):
    """sendBeacon 不可用时的 Image 兜底上报。"""
    if not data:
        return JSONResponse({"ok": False, "error": "missing data"}, status_code=400)
    if len(data.encode("utf-8")) > MAX_BODY_BYTES:
        return JSONResponse({"ok": False, "error": "payload too large"}, status_code=413)
    try:
        payload = json.loads(data)
    except Exception:
        return JSONResponse({"ok": False, "error": "bad data"}, status_code=400)
    return await ingest(payload, request)


@app.get("/health")
async def health():
    return {"status": "ok", "db": str(DB_PATH)}


@app.get("/")
async def index():
    return RedirectResponse("/dashboard")


@app.get("/dashboard")
async def dashboard_page():
    return FileResponse(BASE_DIR / "dashboard.html")


def query(sql: str, params: tuple = ()) -> list:
    conn = connect()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


@app.get("/api/overview")
async def overview(days: int = 7):
    days = max(1, min(90, days))
    since_ms = int(__import__("time").time() * 1000) - days * 86400 * 1000
    rows = query(
        """
        SELECT date(ts/1000.0, 'unixepoch', 'localtime') AS day,
               SUM(CASE WHEN event_type='page_view' THEN 1 ELSE 0 END) AS pv,
               COUNT(DISTINCT CASE WHEN event_type='page_view' THEN visitor_id END) AS uv,
               COUNT(DISTINCT CASE WHEN event_type='page_view' THEN ip_hash END) AS ips,
               SUM(CASE WHEN event_type='page_view' AND is_bot=1 THEN 1 ELSE 0 END) AS bot_pv,
               COUNT(DISTINCT CASE WHEN event_type='click' THEN session_id END) AS click_sessions
        FROM events
        WHERE ts >= ?
        GROUP BY day
        ORDER BY day
        """,
        (since_ms,),
    )
    avg = query(
        """
        SELECT
          AVG(CAST(json_extract(payload_json, '$.durationMs') AS REAL)) AS avg_duration_ms,
          AVG(CAST(json_extract(payload_json, '$.lcp') AS REAL)) AS avg_lcp_ms,
          AVG(CAST(json_extract(payload_json, '$.ttfb') AS REAL)) AS avg_ttfb_ms,
          AVG(CAST(json_extract(payload_json, '$.inp') AS REAL)) AS avg_inp_ms,
          AVG(CAST(json_extract(payload_json, '$.longTasks') AS REAL)) AS avg_long_tasks
        FROM events
        WHERE event_type='page_exit' AND ts >= ?
        """,
        (since_ms,),
    )
    top_pages = query(
        """
        SELECT page, COUNT(*) AS cnt
        FROM events
        WHERE event_type='page_view' AND ts >= ?
        GROUP BY page
        ORDER BY cnt DESC
        LIMIT 10
        """,
        (since_ms,),
    )
    return {
        "days": [dict(r) for r in rows],
        "averages": dict(avg[0]) if avg else {},
        "topPages": [dict(r) for r in top_pages],
    }


@app.get("/api/recent")
async def recent(limit: int = 20):
    limit = max(1, min(200, limit))
    rows = query(
        """
        SELECT event_type, ts, visitor_id, session_id, page, device, os, browser,
               ip_hash, bot_score, is_bot, payload_json
        FROM events
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return {"events": [dict(r) for r in rows]}


def _round(v, ndigits: int = 1):
    return round(v, ndigits) if v is not None else None


@app.get("/api/dashboard")
async def dashboard_data(days: int = 7):
    """看板聚合接口：一次返回全部图表所需数据。"""
    days = max(1, min(90, days))
    since_ms = int(time.time() * 1000) - days * 86400 * 1000

    totals = query(
        """
        SELECT
          SUM(CASE WHEN event_type='page_view' THEN 1 ELSE 0 END) AS pv,
          COUNT(DISTINCT CASE WHEN event_type='page_view' THEN visitor_id END) AS uv,
          COUNT(DISTINCT CASE WHEN event_type='page_view' THEN ip_hash END) AS ips,
          COUNT(DISTINCT CASE WHEN event_type='page_view' THEN session_id END) AS sessions,
          SUM(CASE WHEN event_type='click' THEN 1 ELSE 0 END) AS clicks,
          COUNT(DISTINCT CASE WHEN event_type='click' THEN session_id END) AS click_sessions,
          SUM(CASE WHEN event_type='js_error' THEN 1 ELSE 0 END) AS js_errors,
          SUM(CASE WHEN event_type='resource_error' THEN 1 ELSE 0 END) AS resource_errors,
          SUM(CASE WHEN event_type='page_view' AND is_bot=1 THEN 1 ELSE 0 END) AS bot_pv,
          SUM(CASE WHEN event_type='page_exit' AND json_extract(payload_json, '$.longTasks') > 0
              THEN 1 ELSE 0 END) AS lag_sessions,
          SUM(CASE WHEN event_type='page_exit' THEN 1 ELSE 0 END) AS exit_sessions
        FROM events
        WHERE ts >= ?
        """,
        (since_ms,),
    )
    avg = query(
        """
        SELECT
          AVG(CAST(json_extract(payload_json, '$.durationMs') AS REAL)) AS avg_duration_ms,
          AVG(CAST(json_extract(payload_json, '$.activeMs') AS REAL)) AS avg_active_ms,
          AVG(CAST(json_extract(payload_json, '$.ttfb') AS REAL)) AS avg_ttfb,
          AVG(CAST(json_extract(payload_json, '$.fcp') AS REAL)) AS avg_fcp,
          AVG(CAST(json_extract(payload_json, '$.lcp') AS REAL)) AS avg_lcp,
          AVG(CAST(json_extract(payload_json, '$.inp') AS REAL)) AS avg_inp,
          AVG(CAST(json_extract(payload_json, '$.cls') AS REAL)) AS avg_cls,
          AVG(CAST(json_extract(payload_json, '$.longTasks') AS REAL)) AS avg_long_tasks
        FROM events
        WHERE event_type='page_exit' AND ts >= ?
        """,
        (since_ms,),
    )
    daily = query(
        """
        SELECT date(ts/1000.0, 'unixepoch', 'localtime') AS day,
          SUM(CASE WHEN event_type='page_view' THEN 1 ELSE 0 END) AS pv,
          COUNT(DISTINCT CASE WHEN event_type='page_view' THEN visitor_id END) AS uv,
          COUNT(DISTINCT CASE WHEN event_type='page_view' THEN ip_hash END) AS ips,
          SUM(CASE WHEN event_type='click' THEN 1 ELSE 0 END) AS clicks,
          SUM(CASE WHEN event_type='page_view' AND is_bot=1 THEN 1 ELSE 0 END) AS bot_pv,
          SUM(CASE WHEN event_type IN ('js_error', 'resource_error') THEN 1 ELSE 0 END) AS errors
        FROM events
        WHERE ts >= ?
        GROUP BY day
        ORDER BY day
        """,
        (since_ms,),
    )
    devices = query(
        "SELECT device AS name, COUNT(*) AS value FROM events "
        "WHERE event_type='page_view' AND ts >= ? GROUP BY device ORDER BY value DESC",
        (since_ms,),
    )
    os_rows = query(
        "SELECT os AS name, COUNT(*) AS value FROM events "
        "WHERE event_type='page_view' AND ts >= ? GROUP BY os ORDER BY value DESC",
        (since_ms,),
    )
    browsers = query(
        "SELECT browser AS name, COUNT(*) AS value FROM events "
        "WHERE event_type='page_view' AND ts >= ? GROUP BY browser ORDER BY value DESC",
        (since_ms,),
    )
    hours = query(
        """
        SELECT CAST(strftime('%H', ts/1000.0, 'unixepoch', 'localtime') AS INTEGER) AS hour,
               COUNT(*) AS pv
        FROM events
        WHERE event_type='page_view' AND ts >= ?
        GROUP BY hour
        ORDER BY hour
        """,
        (since_ms,),
    )
    top_pages = query(
        """
        SELECT page, COUNT(*) AS pv, COUNT(DISTINCT visitor_id) AS uv
        FROM events
        WHERE event_type='page_view' AND ts >= ?
        GROUP BY page
        ORDER BY pv DESC
        LIMIT 10
        """,
        (since_ms,),
    )
    recent_rows = query(
        """
        SELECT event_type, ts, visitor_id, page, device, os, browser, bot_score, is_bot
        FROM events
        ORDER BY id DESC
        LIMIT 20
        """
    )

    t = dict(totals[0]) if totals else {}
    a = dict(avg[0]) if avg else {}
    pv = t.get("pv") or 0
    sessions = t.get("sessions") or 0
    exit_sessions = t.get("exit_sessions") or 0

    return {
        "days": days,
        "generatedAt": int(time.time() * 1000),
        "totals": {
            "pv": pv,
            "uv": t.get("uv") or 0,
            "ips": t.get("ips") or 0,
            "sessions": sessions,
            "clicks": t.get("clicks") or 0,
            "clickSessions": t.get("click_sessions") or 0,
            "jsErrors": t.get("js_errors") or 0,
            "resourceErrors": t.get("resource_errors") or 0,
            "botPv": t.get("bot_pv") or 0,
            "botRatio": _round((t.get("bot_pv") or 0) / pv, 4) if pv else None,
            "clickRate": _round((t.get("click_sessions") or 0) / sessions, 4) if sessions else None,
            "lagSessionRatio": _round((t.get("lag_sessions") or 0) / exit_sessions, 4) if exit_sessions else None,
            "avgDurationMs": _round(a.get("avg_duration_ms")),
            "avgActiveMs": _round(a.get("avg_active_ms")),
            "avgTtfb": _round(a.get("avg_ttfb")),
            "avgFcp": _round(a.get("avg_fcp")),
            "avgLcp": _round(a.get("avg_lcp")),
            "avgInp": _round(a.get("avg_inp")),
            "avgCls": _round(a.get("avg_cls"), 3),
            "avgLongTasks": _round(a.get("avg_long_tasks"), 2),
        },
        "daily": [dict(r) for r in daily],
        "devices": [dict(r) for r in devices],
        "os": [dict(r) for r in os_rows],
        "browsers": [dict(r) for r in browsers],
        "hours": [dict(r) for r in hours],
        "topPages": [dict(r) for r in top_pages],
        "recent": [dict(r) for r in recent_rows],
    }


if __name__ == "__main__":
    import uvicorn

    init_db()
    uvicorn.run(app, host="127.0.0.1", port=8000)
