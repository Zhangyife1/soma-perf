#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地一键演示：生成演示数据并启动看板。

用法：
  python run_local.py          # 首次自动生成 14 天演示数据
  python run_local.py --force  # 清空并重新生成演示数据

启动后浏览器打开：http://127.0.0.1:8000/dashboard
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVER = ROOT / "server"

os.environ.setdefault("SOMA_DB", str(SERVER / "soma_perf_local.db"))
os.environ.setdefault("SOMA_IP_SALT", "local-demo-salt")
os.environ.setdefault("SOMA_SITE_TOKEN", "")
sys.path.insert(0, str(SERVER))

import collect  # noqa: E402
import seed_demo  # noqa: E402

force = "--force" in sys.argv
if force or not Path(os.environ["SOMA_DB"]).exists():
    seed_demo.seed(force=True, days=14)
else:
    print("已存在演示数据库，跳过生成（加 --force 可重新生成）")

import uvicorn  # noqa: E402

port = int(os.environ.get("PORT", "8000"))
print(f"\nSomaPerf 看板地址：http://127.0.0.1:{port}/dashboard")
uvicorn.run(collect.app, host="127.0.0.1", port=port)
