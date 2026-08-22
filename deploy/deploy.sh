#!/usr/bin/env bash
# SomaPerf 一键部署脚本（在阿里云 ECS 上运行）
# 用法：
#   sudo bash deploy.sh
# 可选环境变量：
#   APP_DIR      部署目录，默认 /opt/soma-perf
#   SITE_JS_DIR  网站静态目录（放 soma-perf.js），默认 /www/wwwroot/www.somaagent.com.cn/js
#   SOMA_IP_SALT IP 哈希盐，默认自动生成
#   PORT         采集服务端口，默认 8000
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/soma-perf}"
SITE_JS_DIR="${SITE_JS_DIR:-/www/wwwroot/www.somaagent.com.cn/js}"
PORT="${PORT:-8000}"
IP_SALT="${SOMA_IP_SALT:-$(head -c 24 /dev/urandom | base64)}"
if [ -z "${SOMA_SITE_TOKEN:-}" ]; then
  SOMA_SITE_TOKEN="$(openssl rand -hex 16 2>/dev/null || head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
fi

if [ "$(id -u)" -ne 0 ]; then
  echo "请用 root 或 sudo 运行"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "未找到 python3，请先安装 Python 3"
  exit 1
fi

echo "==> 创建目录"
mkdir -p "$APP_DIR/server" "$SITE_JS_DIR"

echo "==> 复制采集服务"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "$SCRIPT_DIR/../server/collect.py" "$SCRIPT_DIR/../server/requirements.txt" "$APP_DIR/server/"

echo "==> 复制埋点脚本到网站目录"
if [ -f "$SITE_JS_DIR/soma-perf.js" ]; then
  cp "$SITE_JS_DIR/soma-perf.js" "$SITE_JS_DIR/soma-perf.js.bak-$(date +%F)"
  echo "    已备份原文件：$SITE_JS_DIR/soma-perf.js.bak-$(date +%F)"
fi
cp "$SCRIPT_DIR/../sdk/soma-perf.js" "$SITE_JS_DIR/soma-perf.js"

echo "==> 创建 Python 虚拟环境并安装依赖"
if [ ! -d "$APP_DIR/venv" ]; then
  python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/server/requirements.txt"

echo "==> 写入 systemd 服务"
cat > /etc/systemd/system/soma-perf.service <<EOF
[Unit]
Description=SomaPerf Collector
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR/server
Environment=SOMA_IP_SALT=$IP_SALT
Environment=SOMA_DB=$APP_DIR/server/soma_perf.db
Environment=SOMA_SITE_TOKEN=$SOMA_SITE_TOKEN
ExecStart=$APP_DIR/venv/bin/uvicorn collect:app --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable soma-perf
systemctl restart soma-perf

echo "==> 生成 Nginx 片段"
if [ -d "/www/server/nginx/conf" ]; then
  SNIPPET_DIR="/www/server/nginx/conf/snippets"
else
  SNIPPET_DIR="/etc/nginx/snippets"
fi
mkdir -p "$SNIPPET_DIR"
cat > "$SNIPPET_DIR/soma-perf-collect.conf" <<EOF
location /collect {
    proxy_pass http://127.0.0.1:$PORT;
    client_max_body_size 256k;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-For \$remote_addr;
    proxy_set_header X-Real-IP \$remote_addr;
}
EOF

cat > "$SNIPPET_DIR/soma-perf-ratelimit.conf" <<'EOF'
# 可选：防止 /collect 被刷量。
# 把这个文件 include 到 nginx 主配置的 http 块：
#   include snippets/soma-perf-ratelimit.conf;
# 并在上面 location /collect 中加入一行：
#   limit_req zone=soma_perf burst=20 nodelay;
limit_req_zone $binary_remote_addr zone=soma_perf:10m rate=30r/m;
EOF

echo ""
echo "部署完成，接下来手动做两步："
echo "1. 宝塔后台：网站 -> 找到 somaagent -> 设置 -> 配置文件，"
echo "   在 server { } 块内加入下面这行（或直接把 location 块粘贴进去）："
echo "     include $SNIPPET_DIR/soma-perf-collect.conf;"
echo "   保存后点击「重载配置」；Nginx 会先校验语法，出错不会生效。"
echo "2. WordPress 埋点（已复制到 $SITE_JS_DIR/soma-perf.js）："
echo "     推荐用 WPCode 插件新建 PHP Snippet，粘贴 deploy/wp-functions-snippet.php 内容并启用；"
echo "     启用前在 Snippet 顶部加三行常量（Token 请勿公开）："
echo "       define('SOMA_PERF_ENDPOINT', 'https://www.somaagent.com.cn/collect');"
echo "       define('SOMA_PERF_SITE_ID', 'somaagent');"
echo "       define('SOMA_PERF_TOKEN', '$SOMA_SITE_TOKEN');"
echo "     可选 define('SOMA_PERF_DEFER', true); 开启零阻塞加载。"
echo "     或者把该内容追加到子主题 functions.php。"
echo ""
echo "注意：/collect 已启用站点令牌校验，请勿把 Token 写进公开页面源码。"
echo ""
echo "验证：curl http://127.0.0.1:$PORT/health"
