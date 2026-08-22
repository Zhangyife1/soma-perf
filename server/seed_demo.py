#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成模拟埋点数据，用于本地跑通「埋点 → 采集 → 看板」闭环。

用法：
  python seed_demo.py --force --days 14
"""
import argparse
import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import collect

PAGES = [
    ("/", 30),
    ("/product", 22),
    ("/about", 14),
    ("/news", 10),
    ("/contact", 8),
    ("/app-download", 8),
    ("/privacy", 4),
]

PROFILES = [
    {
        "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.49",
        "browser": "wechat", "os": "ios", "device": "mobile", "weight": 20,
    },
    {
        "ua": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36",
        "browser": "chrome", "os": "android", "device": "mobile", "weight": 30,
    },
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "browser": "chrome", "os": "windows", "device": "pc", "weight": 22,
    },
    {
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "browser": "safari", "os": "macos", "device": "pc", "weight": 10,
    },
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 Edg/126.0",
        "browser": "edge", "os": "windows", "device": "pc", "weight": 8,
    },
    {
        "ua": "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
        "browser": "safari", "os": "ios", "device": "tablet", "weight": 5,
    },
]

BOT_PROFILES = [
    "Mozilla/5.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "python-requests/2.31.0",
]

REFERRERS = [
    "",
    "https://www.baidu.com/s?wd=soma+ai",
    "https://mp.weixin.qq.com/",
    "https://www.somaagent.com.cn/news",
    "https://www.google.com/search?q=somaagent",
]

CLICK_SELECTORS = [
    "#nav-product", ".hero .btn-primary", "#contact-form button",
    "a[data-event=download]", ".news-item:first-child a", "footer a",
    ".banner .btn", "#nav-about",
]

HOUR_WEIGHTS = [
    1, 1, 1, 1, 2, 2, 3, 5, 7, 9, 10, 11, 12, 11, 10, 10, 11, 12, 11, 9, 7, 5, 3, 2,
]


def pick_page():
    pages = [p for p, _ in PAGES]
    weights = [w for _, w in PAGES]
    return random.choices(pages, weights=weights)[0]


def perf_values():
    return {
        "ttfb": random.randint(120, 900),
        "fcp": random.randint(500, 2200),
        "lcp": random.randint(900, 3800),
        "cls": round(random.uniform(0, 0.25), 3),
        "inp": random.randint(60, 400),
    }


def seed(force: bool = False, days: int = 14) -> dict:
    db = Path(collect.DB_PATH)
    if force:
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(db) + suffix)
            if p.exists():
                p.unlink()

    collect.init_db()
    random.seed(20260822)
    today = datetime.now().date()
    all_events = 0
    visits = 0
    bot_visits = 0

    for day_offset in range(days - 1, -1, -1):
        day = today - timedelta(days=day_offset)
        visit_count = random.randint(45, 110)
        day_visitors = random.randint(25, 60)
        day_ips = random.randint(15, 35)
        ip_pool = [f"10.{random.randint(1, 255)}.{random.randint(1, 255)}.{random.randint(1, 255)}" for _ in range(day_ips)]

        for i in range(visit_count):
            is_bot = random.random() < 0.10
            if is_bot:
                profile = {
                    "ua": random.choice(BOT_PROFILES),
                    "browser": "other", "os": "other", "device": "pc",
                }
                bot_visits += 1
            else:
                profile = random.choices(PROFILES, weights=[p["weight"] for p in PROFILES])[0]

            hour = random.choices(range(24), weights=HOUR_WEIGHTS)[0]
            minute = random.randint(0, 59)
            second = random.randint(0, 59)
            ts = int(datetime(day.year, day.month, day.day, hour, minute, second).timestamp() * 1000)
            visitor = f"v_{day.strftime('%m%d')}_{random.randint(0, day_visitors)}"
            session = f"s_{day.strftime('%m%d')}_{i}"
            page = pick_page() if not is_bot else "/"
            ip = random.choice(ip_pool)
            perf = perf_values()

            base = {
                "type": "page_view", "ts": ts, "siteId": "somaagent",
                "visitorId": visitor, "sessionId": session, "page": page,
                "referrer": random.choice(REFERRERS),
                "ua": profile["ua"], "device": profile["device"],
                "os": profile["os"], "browser": profile["browser"],
                "isWechat": 1 if profile["browser"] == "wechat" else 0,
                "uaBot": 1 if is_bot else 0,
                "viewport": "390x844" if profile["device"] == "mobile" else "1440x900",
                "lang": "zh-CN",
                "botHints": {"webdriver": False, "languages": 1, "plugins": 5},
                "ttfb": perf["ttfb"], "fcp": perf["fcp"],
            }
            events = [dict(base)]

            if not is_bot:
                click_count = random.choices([0, 1, 2, 3, 4, 6], weights=[25, 30, 22, 13, 7, 3])[0]
                for c in range(click_count):
                    click_ts = ts + 8000 + c * random.randint(5000, 30000)
                    events.append({
                        "type": "click", "ts": click_ts, "siteId": "somaagent",
                        "visitorId": visitor, "sessionId": session, "page": page,
                        "referrer": "", "ua": profile["ua"], "device": profile["device"],
                        "os": profile["os"], "browser": profile["browser"],
                        "x": random.randint(10, 1200), "y": random.randint(10, 800),
                        "tag": "a" if c % 2 == 0 else "button",
                        "text": "点击测试", "selector": random.choice(CLICK_SELECTORS),
                    })

                if random.random() < 0.04:
                    events.append({
                        "type": "js_error", "ts": ts + random.randint(3000, 20000),
                        "siteId": "somaagent", "visitorId": visitor, "sessionId": session,
                        "page": page, "ua": profile["ua"], "message": "demo error",
                        "source": "inline", "line": 12,
                    })
                if random.random() < 0.02:
                    events.append({
                        "type": "resource_error", "ts": ts + random.randint(3000, 20000),
                        "siteId": "somaagent", "visitorId": visitor, "sessionId": session,
                        "page": page, "ua": profile["ua"], "url": "https://cdn.example.com/x.png",
                    })

            long_tasks = random.choices([0, 1, 2, 3], weights=[72, 18, 7, 3])[0]
            duration = random.randint(8000, 90000) if click_count == 0 and not is_bot else random.randint(40000, 300000)
            if is_bot:
                duration = random.randint(2000, 15000)
            events.append({
                "type": "page_exit", "ts": ts + duration, "siteId": "somaagent",
                "visitorId": visitor, "sessionId": session, "page": page,
                "ua": profile["ua"], "device": profile["device"],
                "os": profile["os"], "browser": profile["browser"],
                "durationMs": duration, "activeMs": duration - random.randint(0, 30000),
                "clicks": click_count if not is_bot else 0,
                "scrollDepth": random.randint(20, 100) if not is_bot else 5,
                "longTasks": long_tasks,
                "longTaskMs": long_tasks * random.randint(60, 400),
                "fcp": perf["fcp"], "lcp": perf["lcp"], "cls": perf["cls"],
                "inp": perf["inp"], "ttfb": perf["ttfb"],
            })

            collect.save_events(events, ip)
            all_events += len(events)
            visits += 1

    summary = {"visits": visits, "bot_visits": bot_visits, "events": all_events, "days": days}
    print(f"演示数据生成完成：{summary}")
    return summary


def main():
    ap = argparse.ArgumentParser(description="生成 SomaPerf 演示数据")
    ap.add_argument("--force", action="store_true", help="清空数据库后重新生成")
    ap.add_argument("--days", type=int, default=14, help="生成最近 N 天数据")
    args = ap.parse_args()
    seed(force=args.force, days=args.days)


if __name__ == "__main__":
    main()
