# JM娘 · 在 QQ 群里轻松搜索和下载禁漫本子的机器人
# Create a QQ bot and add it to the group chat to easily search for JM doujinshi

> 📖 本文档为中英双语 / This document is bilingual (中文 | English)

一个 Python QQ 群机器人（**JM娘**）：群成员在群里 `@机器人` 即可搜索和下载 [jmcomic](https://github.com/tonquer/jmcomic) 支持的漫画本子。
A Python QQ group bot (**JM娘**) that lets group members search and download doujinshi from [jmcomic](https://github.com/tonquer/jmcomic)-supported sources directly in a QQ group chat — by simply mentioning the bot.

> ⚠️ **法律声明**：本项目仅供**学习交流**。涉及成人内容，请务必遵守你所在地区的法律法规与相关平台服务条款；使用非官方客户端/自动化工具存在账号被封风险。请勿用于任何非法用途。
> ⚠️ **Legal disclaimer**: This project is for **educational purposes only**. Adult content is involved; you are solely responsible for complying with the laws of your region and the terms of service of the platforms involved. Using unofficial clients/automation carries a real risk of account bans. Do not use this bot for any illegal activity.

## 功能 Features

群成员 `@机器人` + 命令 / Mention the bot (`@bot`) followed by a command:

| 命令 Command | 说明（中文） | Description (EN) |
|---|---|---|
| `@bot <漫画ID>` | 下载整本漫画 → 打包 ZIP → 上传群文件 + 发浏览器下载链接 | Downloads the entire album, packs it into one ZIP, uploads it to group files and sends a browser download link |
| `@bot <关键词/名称>` | 搜索并返回最新 **5 本（含ID）**，支持翻页 | Searches and returns the latest **5 results with IDs** (paginated) |
| `@bot 作者 <作者名>` | 按**作者**搜索，返回 5 本（含ID） | Searches by **author** and returns 5 results with IDs |
| `@bot 随机` | 从近 30 天最火的本子里随机推荐一本 | Random recommendation from the hottest albums of the last 30 days |
| `@bot 下一页` | 查看上一次搜索的下一页；**直接发「下一页」即可（无需@机器人）** | Next page of the last search; **just send `下一页` — no mention needed** |
| `@bot 取消` | 取消正在进行的下载 | Cancels the in-progress download |
| `@bot 说明` | 查看使用说明 | Shows the help text |

## 亮点 Highlights

- **智能中日文搜索 Smart CJK search** — 用简体中文搜索会自动匹配繁体/日文汉字/假名标题，通过 4 层降级机制：
  Searching with Simplified Chinese automatically matches Traditional Chinese / Japanese kanji / kana titles through a 4-layer fallback:
  1. 简→繁转换（`zhconv`）/ Simplified → Traditional conversion (`zhconv`)
  2. 汉字异体映射（如 `琉→瑠`、`绘→絵`）/ Hanzi variant map (e.g. `琉 → 瑠`, `绘 → 絵`)
  3. 中文虚词→日文假名（如 `与/和→と`、`的/之→の`——搜「枫与铃」能找到「楓と鈴」）/ Chinese function words → Japanese kana (e.g. `与/和 → と`, `的/之 → の` — searching `枫与铃` finds `楓と鈴`)
  4. 核心字降级搜索：拆词逐字搜索，标题含全部核心字即命中（无字典依赖的普适兜底）/ Core-character degraded search: split the query into core characters, search each, keep titles containing all of them (dictionary-free universal fallback)
- **搜索结果翻页 Paginated results** — 每页 5 本，直接发「下一页」翻完所有匹配本子（无需@机器人）/ 5 per page, just send `下一页` (no mention needed) to page through all matched albums
- **加密 ZIP（AES-128）Encrypted ZIPs** — QQ 上传会扫描 ZIP 内容并静默删除成人文件；加密使扫描失效，上传得以存活（实测：未加密上传 `retcode=1200`，AES 加密 `retcode=0`）/ QQ scans ZIP contents on upload and silently deletes adult files; encryption makes the scan fail, so uploads survive (verified: unencrypted → `retcode=1200`, AES-encrypted → `retcode=0`)
- **浏览器下载链接 Browser download links** — 每次下载附带 HTTP 直链兜底 / every download also gets an HTTP link as a fallback
- **CQ 码转义 CQ-code escaping** — 用户可控字符串回显前转义，群成员无法用 `[CQ:...]` 让机器人 @全体/冒名发图 / user-controlled strings are escaped before being echoed, so group members can't make the bot `@all` or send fake images via `[CQ:...]`
- **每群限流 Per-group rate limiting** — 搜索类命令 10 秒冷却 / 10 s cooldown on search requests
- **进度汇报 / 排队 / 自动清理 Progress reports** (25/50/75%), queueing (2 concurrent downloads), 7-day auto-cleanup

## 架构 Architecture

```
QQ 群聊天
QQ group chat
    │  OneBot v11 (WebSocket)
    ▼
NapCat（QQ 机器人运行时）── ws://127.0.0.1:8081 ──►  JM 机器人（Python，本仓库）
NapCat (QQ bot runtime)                            JM bot (Python, this repo)
                                                        │
                                        jmcomic ──► 下载整本 ──► AES ZIP
                                                     download album ──► AES ZIP
                                                        │
                          upload_group_file ──► QQ 群文件 / group files
                          publish token URL  ──► http.server :8080
```

## 环境要求 Requirements

- **NapCat**（或任意 OneBot v11 实现）+ 一个已登录的 QQ 账号 / **NapCat** (or any OneBot v11 implementation) with a QQ account logged in
- Python 3.10+
- 依赖 Dependencies：

```bash
pip install -r requirements.txt
```

## 部署 Setup

### 1. 安装 NapCat 并配置 OneBot WebSocket

安装对应平台的 NapCat（见 NapCat 官方文档），用机器人 QQ 号扫码登录一次，然后在 NapCat 里新增一个 OneBot v11 **正向 WebSocket 服务端**，监听 `ws://127.0.0.1:8081`（机器人主动连它）。可选：调高 OneBot 配置里的上传限速（`uploadSpeedKBps`）。

Install NapCat for your platform (see the official NapCat docs), log in with the bot's QQ account (scan the QR code once), then create an OneBot v11 **forward WebSocket server** listening on `ws://127.0.0.1:8081` (the bot connects out to it). Optionally raise the upload speed limit (`uploadSpeedKBps`) in NapCat's OneBot config.

### 2. 配置机器人

敏感值通过**环境变量**读取（不写死在代码里）。Sensitive values are read from environment variables (never hard-coded):

| 变量 Variable | 含义 Meaning |
|---|---|
| `JM_ZIP_PASSWORD` | 上传 ZIP 的 AES 密码（需告知用户）/ AES password for uploaded ZIPs (must be shared with users) |
| `JM_PUBLIC_IP` | 服务器公网 IP/域名，用于生成浏览器下载链接 / public IP/host of this server, used to build browser download links |
| `JM_PROXY` | 可选 HTTP 代理（如 `http://127.0.0.1:7890`；留空=直连）/ optional HTTP proxy for jmcomic (empty = direct) |

用 HTTP 服务托管下载目录（8080 端口）：Serve the download directory over HTTP on port 8080:

```bash
mkdir -p http_dl
python3 -m http.server 8080 --bind 0.0.0.0 --directory http_dl
```

### 3. 运行

```bash
python jm_niang.py
```

或使用 systemd 服务（推荐）Or as a systemd service (recommended):

```ini
# /etc/systemd/system/jmniang.service
[Unit]
Description=JM Niang QQ Bot (download comic -> zip -> upload)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/jmniang
Environment=JM_ZIP_PASSWORD=YOUR_PASSWORD
Environment=JM_PUBLIC_IP=YOUR_SERVER_IP
ExecStart=/usr/bin/python3 -u /opt/jmniang/jm_niang.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now jmniang
```

### 4. 可选：群白名单

编辑 `jm_niang.py` 里的 `ALLOWED_GROUPS` 可限制使用机器人的群（空列表 = 所有群可用）。
Edit `ALLOWED_GROUPS` in `jm_niang.py` to restrict which QQ groups may use the bot (empty list = all groups).

## 测试 Tests

```bash
python -m pytest test_jm_download.py
```

覆盖：ZIP 加密、CQ 转义、搜索变体生成、作者命令解析、翻页渲染、消息层全命令路由（全部离线，无需联网）。
Covers ZIP encryption, CQ escaping, search-variant generation, author command parsing, pagination rendering and message-layer command routing (all offline, no network needed).

## 排障 Troubleshooting

| 症状 Symptom | 原因与处理 Cause / fix |
|---|---|
| 机器人在群里没有反应 / Bot is silent in the group | QQ 账号被踢下线（NapCat 进程还活着）。快速探针：通过 WS 调 `send_group_msg`，返回 `retcode=1200 ... NodeIKernelMsgService` 超时 = QQ 内核已死 → 重启 NapCat 并重新扫码 / The QQ account was likely kicked offline (NapCat stays alive). Probe: call `send_group_msg` over WS; `retcode=1200 ... NodeIKernelMsgService` timeout means the QQ kernel is dead → restart NapCat and re-scan the QR code |
| 群文件上传失败 / Group file upload fails | QQ 会扫描 ZIP 内容并拒绝成人图片 → 保持 `ZIP_ENCRYPT = True`（AES-128）；用户需用 WinRAR / 7-Zip / ZArchiver 解压 / QQ scans ZIP contents and rejects adult images → keep `ZIP_ENCRYPT = True` (AES-128); users need WinRAR / 7-Zip / ZArchiver to extract |
| 明明存在的本子搜不到 / Search finds nothing for a known title | 站内搜索是精确子串匹配；4 层降级已覆盖简体/繁体/日文写法，但超冷门的单字组合仍可能漏（见 `jm_download.py` 的 `_search_by_core_chars`）/ The site search is exact substring matching; the 4-layer fallback covers Simplified/Traditional/Japanese writing, but ultra-rare single-character combos may still miss (see `_search_by_core_chars` in `jm_download.py`) |

## 项目结构 Project layout

```
jm_niang.py          # QQ 机器人主循环：OneBot WS 客户端、命令处理、上传、翻页
                     # QQ bot main loop: OneBot WS client, command handling, uploads, pagination
jm_download.py       # jmcomic 封装：下载→AES ZIP、智能搜索（变体+翻页）、缓存、清理
                     # jmcomic wrapper: download → AES ZIP, smart search (variants + pagination), cache, cleanup
test_jm_download.py  # 离线单元测试 / offline unit tests
start_jmniang.bat    # 可选 Windows 启动脚本 / optional Windows launcher
```

## License

MIT — 见 [LICENSE](LICENSE) / see [LICENSE](LICENSE).
