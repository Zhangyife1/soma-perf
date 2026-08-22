# SomaPerf 网站实时性能与访问监测系统

面向 www.somaagent.com.cn 的轻量监测系统，包含：

- 前端埋点 SDK（真实用户性能 + 行为 + 卡顿 + Bot 信号）
- 采集服务（FastAPI + SQLite，单机即可支撑日 PV 100 的规模）
- Nginx 日志解析脚本（与埋点数据交叉验证）
- 后续可扩展：主动探测（Playwright）、看板、告警

## 目录结构

```text
perf-monitor/
├── sdk/soma-perf.js        # 前端埋点脚本，可直接引入或内联
├── server/collect.py       # 采集 API + SQLite 存储 + 概览接口
├── server/requirements.txt
├── server/parse_nginx.py   # Nginx access.log 按日汇总
├── server/dashboard.html   # ECharts 看板页面（暗色，GEO 看板同风格）
├── server/seed_demo.py     # 本地演示数据生成器
├── run_local.py            # 本地一键演示：生成数据 + 启动看板
├── .gitignore
├── deploy/                 # 一键部署包（ECS 上用）
│   ├── deploy.sh           # 安装服务 + 复制 SDK + 生成 Nginx 片段
│   ├── verify.sh           # 部署后自检
│   ├── insert-snippet.html # 非 WordPress 静态页的头部代码
│   └── wp-functions-snippet.php # WordPress 埋点代码（WPCode / functions.php）
└── examples/test.html      # 本地测试页
```

## 零、一键部署（推荐）

把整个 `perf-monitor` 目录上传到 ECS（如 `/opt/perf-monitor`），然后：

```bash
cd /opt/perf-monitor
sudo bash deploy/deploy.sh
```

脚本会自动完成：复制采集服务、复制埋点脚本到网站目录、创建虚拟环境、安装依赖、注册 systemd 服务并启动、生成 Nginx 片段。之后手动两步：

1. 在网站 Nginx server 块里加一行 `include snippets/soma-perf-collect.conf;`，然后 `sudo nginx -t && sudo systemctl reload nginx`；
2. WordPress 埋点：推荐安装 WPCode 插件，新建「PHP Snippet」，粘贴
   `deploy/wp-functions-snippet.php` 的内容并启用；或者把该内容追加到子主题
   `functions.php`。SDK 文件已由脚本复制到网站根目录 `/js/soma-perf.js`，
   无需手动上传。

运行 `sudo bash deploy/verify.sh` 自检；埋点页面上线后，`/api/overview` 就会出现数据。

> 说明：`deploy/insert-snippet.html` 是给非 WordPress 纯静态页面用的；WordPress
> 站点请使用 `wp-functions-snippet.php`，避免主题更新后埋点丢失。

## 稳定性与安全说明

### 对网站性能的影响

- `perf-monitor` 上传到 `/opt/` 后只是磁盘文件，运行时完全不参与网站请求。
- 采集服务只监听 `127.0.0.1:8000`，对外只有 Nginx 代理的 `/collect` 一个路径；
  日 PV 100 规模下占用内存约几十 MB、CPU 可忽略。
- 网站侧新增的只有一个约 13KB 的静态 JS（gzip 后约 5KB）+ 一次同源 POST 上报，
  对页面加载影响 < 1%；需要零阻塞时在 Snippet 里开启 `SOMA_PERF_DEFER`。
- 采集服务异常（崩溃/超时）不会影响网站：Nginx 代理失败只是 `/collect`
  请求失败，页面本身不依赖上报结果。

### 已内置的安全防护

- 站点令牌：`SOMA_SITE_TOKEN` 校验，Token 随事件体发送（不进入 URL，
  避免被 Nginx 日志记录），非法请求返回 403。
- 请求体限制：单次上报最大 256KB（Nginx 与服务端双重限制）。
- 频率限制：同一 IP 每分钟最多 120 条事件；Nginx 层可选 30 次/分钟限流。
- 原始 IP 不落库，只存哈希；管理接口 `/api/*` 不通过 Nginx 对外暴露。
- 数据库放在 `/opt/soma-perf/server/`，不在网站目录内。

### 操作前的备份与回滚

```bash
# 1. ECS 磁盘快照 / 宝塔快照（推荐，最稳）
# 2. 备份 Nginx 配置与网站目录
sudo cp -r /www/server/nginx/conf /www/server/nginx/conf.bak-$(date +%F)
sudo cp -r /www/wwwroot/www.somaagent.com.cn /www/wwwroot/www.somaagent.com.cn.bak-$(date +%F)
# 3. WordPress 数据库备份（宝塔后台或 wp-cli）
```

### 上线顺序（先小范围验证）

1. 先在 ECS 上部署采集服务，`curl /health` 通过；
2. WPCode 里启用 Snippet 时先加条件 `is_front_page()`，只测首页；
3. 打开首页确认 `/api/overview` 出现 page_view，再移除条件全站启用；
4. 保留 Nginx 配置备份一周，确认无异常后再清理。

### Nginx 修改的安全姿势

- 改配置前先备份；每次修改后先 `sudo nginx -t` 再 `systemctl reload nginx`；
- `nginx -t` 报错时不会加载新配置，网站保持旧配置运行；
- reload 是平滑重载，不中断现有连接；
- 如果服务器已有 `/collect` 路径，先 `grep -rn "location /collect" /www/server/nginx` 确认无冲突。

## 零·五、本地看板演示（先跑通闭环）

不需要真实流量也能看完整看板。本地执行：

```bash
cd perf-monitor
python run_local.py
```

首次运行会自动生成最近 14 天的演示数据（约 600 次访问、2000+ 条事件），并启动服务：

- 看板地址：http://127.0.0.1:8000/dashboard
- 聚合接口：http://127.0.0.1:8000/api/dashboard?days=7
- 加 `--force` 可清空并重新生成演示数据

看板包含：PV/UV/独立 IP/Bot 占比/停留时长/卡顿会话占比等指标卡，访问趋势、
设备/浏览器/系统分布、核心性能均值（TTFB/FCP/LCP/INP）、访问时段分布、
Top 页面与最近事件流，每 60 秒自动刷新。

## 一、把埋点脚本插入网站

### 方式 1：新建脚本文件（推荐）

1. 把 `sdk/soma-perf.js` 上传到网站服务器，例如：

   ```text
   /www/wwwroot/www.somaagent.com.cn/js/soma-perf.js
   ```

2. 在网站每个页面的 `<head>` 中（越靠前越好）加入：

   ```html
   <script src="/js/soma-perf.js"></script>
   <script>
   window.SomaPerf.init({
     endpoint: "https://monitor.somaagent.com.cn/collect",
     siteId: "somaagent"
   });
   </script>
   ```

### 方式 2：模板站 / 建站系统

把上面两行加到全局头部模板，例如 WordPress 的 `header.php`、建站工具的「全局头部代码 / 自定义代码」设置，保证全站生效。

### 方式 3：完全内联（不新增文件）

把 `soma-perf.js` 压缩后直接放入 `<script>...</script>`，再在后面加 `window.SomaPerf.init(...)` 配置。

> 提示：如果暂时没有 `monitor.somaagent.com.cn` 域名，可以先在本地测试（见下文「测试」）。

## 二、部署采集服务（阿里云 ECS）

采集服务是一个 FastAPI 应用，放在网站同一台 ECS 上即可。

```bash
cd perf-monitor/server
pip install -r requirements.txt
SOMA_IP_SALT=请改成随机长字符串 uvicorn collect:app --host 127.0.0.1 --port 8000
```

推荐用 systemd 守护进程，并把 `/collect` 反向代理到网站域名下（同源上报，不用处理跨域）：

```nginx
location /collect {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Real-IP $remote_addr;
}
```

然后给站点配上 HTTPS（如 certbot），埋点里把 endpoint 换成 `https://www.somaagent.com.cn/collect`。

## 三、验证是否收到数据

```bash
# 健康检查
curl http://127.0.0.1:8000/health

# 手动模拟一条事件
curl -X POST http://127.0.0.1:8000/collect \
  -H "Content-Type: application/json" \
  -d '[{"type":"page_view","siteId":"somaagent","visitorId":"test","sessionId":"s1","page":"/","ua":"Mozilla/5.0","device":"pc","os":"windows","browser":"chrome"}]'

# 查看概览
curl http://127.0.0.1:8000/api/overview?days=7
```

用浏览器打开 `examples/test.html`，点击页面后到 `http://127.0.0.1:8000/api/recent` 能看到 click、page_exit 等事件。

## 四、接入 Nginx 日志（与埋点交叉验证）

Nginx 访问日志是服务端视角，能验证埋点是否遗漏、统计访问 IP 和 Bot：

```bash
python parse_nginx.py --log /var/log/nginx/access.log --since 2026-08-01 --out csv --csv nginx_daily.csv
python parse_nginx.py --log /var/log/nginx/access.log --since 2026-08-01 --out table
```

> 如果日志格式带 `$request_time`（自定义 log_format），解析器会自动计算平均响应时间；标准 combined 格式也能解析。

## 五、已采集的指标

| 事件类型 | 说明 |
|---|---|
| page_view | PV、UV、设备/系统/浏览器/微信内置、视口、来源、UA 是否 Bot |
| perf | TTFB、FCP、DOM Ready、页面 Load 耗时 |
| click | 点击坐标、元素标签/ID/class、链接、选择器 |
| page_exit | 停留时长、有效时长、滚动深度、长任务数、JS 错误数、LCP/CLS/INP |
| heartbeat | 每 60 秒活跃心跳，兜底停留时长 |
| js_error / resource_error | JS 异常与资源加载失败 |

服务端会对每条事件计算 IP 哈希（不存原始 IP）、Bot 可信分（UA + webdriver + 语言/插件特征），并打上 `is_bot` 标记。

## 六、隐私与合规

- 不存储原始 IP，只存哈希和脱敏后的特征，降低《个人信息保护法》合规风险。
- 建议在网站隐私政策中说明「使用匿名化的行为统计与性能监测数据」。
- 数据默认保留在 ECS 本机 SQLite，后续可加保留周期清理任务。

## 七、下一步（按需开发）

1. 主动探测：Playwright 定时模拟 PC/手机/微信浏览器，输出多平台适配分。
2. 告警：打开率骤降、卡顿率超标、服务器高负载时通知钉钉/企业微信。
3. 周报：每周自动生成性能与访问报告。

## 八、上传 GitHub

```bash
cd perf-monitor
git init
git add .
git commit -m "feat: SomaPerf 网站实时性能与访问监测系统"
git branch -M main
git remote add origin https://github.com/你的用户名/soma-perf.git
git push -u origin main
```

`.gitignore` 已排除本地数据库（`*.db`）、虚拟环境和缓存目录，不会把演示数据推上去。
