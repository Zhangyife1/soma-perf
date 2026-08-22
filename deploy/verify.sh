#!/usr/bin/env bash
# SomaPerf 部署后自检脚本
set -uo pipefail

PORT="${PORT:-8000}"
echo "==> 采集服务健康检查"
curl -sS "http://127.0.0.1:$PORT/health" && echo

echo "==> 概览接口（最近 7 天）"
curl -sS "http://127.0.0.1:$PORT/api/overview?days=7" && echo

echo "==> 最近事件（前 10 条）"
curl -sS "http://127.0.0.1:$PORT/api/recent?limit=10" && echo

echo ""
echo "提示：如果上面都是空数据，说明埋点还没生效，"
echo "请检查网页 <head> 中的脚本与 /js/soma-perf.js 是否存在。"
