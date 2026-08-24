#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 ECS 上的 soma_perf.db 推送到 Render 展示服务（全量替换最近 N 天）。

用法（在 ECS 上，宝塔计划任务每 5 分钟执行一次）：
  python3 /opt/perf-monitor/server/sync_to_render.py \
      --url https://your-app.onrender.com \
      --token <SOMA_SYNC_TOKEN> \
      --days 90
"""
import argparse
import json
import os
import sqlite3
import time
import urllib.request


def main():
    ap = argparse.ArgumentParser(description="同步 SomaPerf 数据到 Render")
    ap.add_argument("--url", required=True, help="Render 服务地址，如 https://xxx.onrender.com")
    ap.add_argument("--token", required=True, help="与 Render 的 SOMA_SYNC_TOKEN 一致")
    ap.add_argument("--days", type=int, default=90, help="推送最近 N 天数据")
    ap.add_argument(
        "--db",
        default=os.environ.get("SOMA_DB", "/opt/soma-perf/server/soma_perf.db"),
        help="ECS 上的数据库路径",
    )
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    since_ms = int(time.time() * 1000) - args.days * 86400 * 1000
    rows = conn.execute(
        """
        SELECT id, site_id, event_type, ts, received_at, visitor_id, session_id,
               page, referrer, ua, device, os, browser, is_wechat, ua_bot,
               viewport, lang, ip_hash, bot_score, is_bot, payload_json
        FROM events
        WHERE ts >= ?
        ORDER BY id
        """,
        (since_ms,),
    ).fetchall()
    conn.close()

    body = json.dumps({"events": [dict(r) for r in rows]}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        args.url.rstrip("/") + "/sync",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Sync-Token": args.token},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    print(f"synced {len(rows)} events -> {result}", flush=True)


if __name__ == "__main__":
    main()
