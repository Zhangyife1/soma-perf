#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析 Nginx access.log，按日输出 PV / 独立 IP / 状态码 / Bot 占比 / 平均响应时间。

用法：
  python parse_nginx.py --log access.log --since 2026-08-01 --out table
  python parse_nginx.py --log access.log --since 2026-08-01 --out csv --csv daily.csv
"""
import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import datetime

LINE_RE = re.compile(
    r'^(\S+) \S+ \S+ \[([^\]]+)\] "(\S+) (\S+) (\S*)" (\d{3}) (\d+|-) "([^"]*)" "([^"]*)"(?:\s+(\S+))?'
)
UA_BOT_RE = re.compile(r"bot|crawl|spider|slurp|headless|phantom|curl|wget|python|scrapy", re.I)


def parse_line(line: str):
    m = LINE_RE.match(line.strip())
    if not m:
        return None
    ip, time_local, method, path, proto, status, size, referer, ua, req_time = m.groups()
    day = "unknown"
    try:
        dt = datetime.strptime(time_local[:20], "%d/%b/%Y:%H:%M:%S")
        day = dt.strftime("%Y-%m-%d")
    except (ValueError, IndexError):
        pass
    return {
        "ip": ip,
        "day": day,
        "method": method,
        "path": path,
        "status": status,
        "referer": referer,
        "ua": ua,
        "request_time": float(req_time) if req_time and req_time != "-" else None,
    }


def summarize(rows, since: str = ""):
    agg = defaultdict(
        lambda: {
            "pv": 0,
            "ips": set(),
            "uas": set(),
            "status": defaultdict(int),
            "rt_sum": 0.0,
            "rt_n": 0,
            "bot": 0,
            "paths": defaultdict(int),
        }
    )
    for r in rows:
        if since and r["day"] < since:
            continue
        d = agg[r["day"]]
        d["pv"] += 1
        d["ips"].add(r["ip"])
        d["uas"].add(r["ua"])
        d["status"][r["status"]] += 1
        if r["request_time"] is not None:
            d["rt_sum"] += r["request_time"]
            d["rt_n"] += 1
        if UA_BOT_RE.search(r["ua"] or ""):
            d["bot"] += 1
        d["paths"][r["path"]] += 1
    return agg


def to_table(agg):
    header = ["日期", "PV", "独立IP", "独立UA", "Bot数", "状态码", "平均响应ms", "Top页面"]
    print("\t".join(header))
    for day in sorted(agg):
        d = agg[day]
        top_path = max(d["paths"], key=d["paths"].get) if d["paths"] else "-"
        avg_rt = f"{d['rt_sum'] / d['rt_n'] * 1000:.1f}" if d["rt_n"] else "-"
        statuses = ",".join(f"{k}:{v}" for k, v in sorted(d["status"].items()))
        print("\t".join([
            day,
            str(d["pv"]),
            str(len(d["ips"])),
            str(len(d["uas"])),
            str(d["bot"]),
            statuses,
            avg_rt,
            top_path,
        ]))


def to_csv(agg, out_path: str):
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["day", "pv", "unique_ips", "unique_uas", "bot_count", "avg_request_time_ms"])
        for day in sorted(agg):
            d = agg[day]
            avg_rt = d["rt_sum"] / d["rt_n"] * 1000 if d["rt_n"] else ""
            w.writerow([day, d["pv"], len(d["ips"]), len(d["uas"]), d["bot"], f"{avg_rt:.1f}" if avg_rt != "" else ""])


def to_json(agg):
    out = {}
    for day in sorted(agg):
        d = agg[day]
        out[day] = {
            "pv": d["pv"],
            "unique_ips": len(d["ips"]),
            "unique_uas": len(d["uas"]),
            "status": dict(d["status"]),
            "bot": d["bot"],
            "avg_request_time_ms": round(d["rt_sum"] / d["rt_n"] * 1000, 1) if d["rt_n"] else None,
            "top_paths": sorted(d["paths"].items(), key=lambda x: x[1], reverse=True)[:10],
        }
    return out


def main():
    ap = argparse.ArgumentParser(description="Nginx access.log 按日汇总")
    ap.add_argument("--log", required=True, help="access.log 路径")
    ap.add_argument("--since", default="", help="只统计该日期及以后，如 2026-08-01")
    ap.add_argument("--out", choices=["table", "csv", "json"], default="table")
    ap.add_argument("--csv", default="", help="csv 输出文件路径")
    args = ap.parse_args()

    rows = []
    with open(args.log, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            r = parse_line(line)
            if r:
                rows.append(r)
    agg = summarize(rows, args.since)
    print(f"解析 {len(rows)} 条有效日志，覆盖 {len(agg)} 天", file=__import__("sys").stderr)
    if args.out == "csv":
        to_csv(agg, args.csv or "nginx_daily.csv")
    elif args.out == "json":
        print(json.dumps(to_json(agg), ensure_ascii=False, indent=2))
    else:
        to_table(agg)


if __name__ == "__main__":
    main()
