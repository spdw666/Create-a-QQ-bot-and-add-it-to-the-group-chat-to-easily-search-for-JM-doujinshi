<div align="center">

# 🤖 JM娘

### Create a QQ bot and add it to the group chat to easily search for JM doujinshi

*在 QQ 群里轻松搜索和下载本子的机器人 · A QQ group bot for searching & downloading doujinshi*

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-2ea44f?style=flat-square)](LICENSE)
[![jmcomic](https://img.shields.io/badge/jmcomic-2.7.4-ff69b4?style=flat-square)](https://github.com/tonquer/jmcomic)
[![OneBot](https://img.shields.io/badge/Protocol-OneBot%20v11-7d3cff?style=flat-square)](https://onebot.dev/)
[![Stars](https://img.shields.io/github/stars/spdw666/Create-a-QQ-bot-and-add-it-to-the-group-chat-to-easily-search-for-JM-doujinshi?style=flat-square&logo=github&logoColor=white)](https://github.com/spdw666/Create-a-QQ-bot-and-add-it-to-the-group-chat-to-easily-search-for-JM-doujinshi)
[![Last commit](https://img.shields.io/github/last-commit/spdw666/Create-a-QQ-bot-and-add-it-to-the-group-chat-to-easily-search-for-JM-doujinshi?style=flat-square&logo=git&logoColor=white)](https://github.com/spdw666/Create-a-QQ-bot-and-add-it-to-the-group-chat-to-easily-search-for-JM-doujinshi)
[![Tests](https://img.shields.io/badge/tests-40%20passed-brightgreen?style=flat-square)](test_jm_download.py)

</div>

---

> 📖 本文档为中英双语，中文在前、English 在后。 · This document is bilingual: Chinese first, English below.

> ⚠️ **法律声明**：本项目仅供**学习交流**。涉及成人内容，请务必遵守你所在地区的法律法规与相关平台服务条款；使用非官方客户端/自动化工具存在账号被封风险。请勿用于任何非法用途。
>
> ⚠️ **Legal disclaimer**: This project is for **educational purposes only**. Adult content is involved; you are solely responsible for complying with the laws of your region and the terms of service of the platforms involved. Using unofficial clients/automation carries a real risk of account bans. Do not use this bot for any illegal activity.

## 目录 · Table of Contents

- [简介 Introduction](#简介-introduction)
- [功能 Features](#功能-features)
- [任务状态与数据 Task state & data](#任务状态与数据-task-state--data)
- [效果示例 Demo](#效果示例-demo)
- [亮点 Highlights](#亮点-highlights)
- [架构 Architecture](#架构-architecture)
- [快速开始 Quick Start](#快速开始-quick-start)
- [详细部署 Deployment](#详细部署-deployment)
- [配置 Configuration](#配置-configuration)
- [运维 Operations](#运维-operations)
- [测试 Tests](#测试-tests)
- [排障 Troubleshooting](#排障-troubleshooting)
- [常见问题 FAQ](#常见问题-faq)
- [项目结构 Project layout](#项目结构-project-layout)
- [更新日志 Changelog](#更新日志-changelog)
- [路线图 Roadmap](docs/roadmap.md)
- [License](#license)

## 简介 Introduction

**JM娘** 是一个 Python QQ 群机器人。群成员在群里 `@机器人` 即可搜索、下载 [jmcomic](https://github.com/tonquer/jmcomic) 支持的漫画本子——输入 ID 下载整本，输入关键词/名称/作者搜索，机器人自动打包加密 ZIP 上传群文件并附带浏览器下载链接。搜索结果、任务和下载记录均按群成员隔离。

**JM娘** is a Python QQ group bot. Group members just `@mention` the bot to search and download doujinshi from [jmcomic](https://github.com/tonquer/jmcomic)-supported sources — send an album ID to download it, or a keyword / title / author to search. The bot packs the album into an encrypted ZIP, uploads it to group files, and attaches a browser download link.

## 功能 Features

群成员 `@机器人` + 命令（只 `@机器人` 不带命令会自动回复按钮菜单）。 · Mention the bot (`@bot`) followed by a command (mentioning `@bot` alone returns the button menu):

| 命令 Command | 说明 | Description |
|---|---|---|
| `@bot <漫画ID>` | 下载整本 → 加密 ZIP → 上传群文件 + 浏览器链接 | Download an album → encrypted ZIP → group files + browser link |
| `@bot 下载 JM123456 第2-5章` / `最新` | 下载指定章节或最新章节；章节缓存与整本缓存隔离 | Download selected or latest chapters; partial caches are isolated from full-album caches |
| `@bot <关键词/名称>` | 搜索，返回最新 5 本（含 ID），可翻页/跳页 | Search and return the latest 5 results with IDs (paginated) |
| `@bot 作者 <作者名>` | 按作者搜索，返回 5 本（含 ID） | Search by author, return 5 results with IDs |
| `@bot 标签 <标签名>` | 按标签搜索（人妻/百合等），返回 5 本（含 ID） | Search by tag, return 5 results with IDs |
| `@bot 日榜/周榜/月榜` | 查看排行榜前 5（支持翻页） | Daily / weekly / monthly ranking top 5 (paginated) |
| `@bot <图片>` | 以图搜本：OCR 文字优先 → SauceNAO / E-Hentai / iQDB 并行识图 → Qwen3-VL 结构化提取标题/作者/标签正向搜禁漫兜底；同图结果缓存秒回 | Reverse image search: OCR text first → SauceNAO / E-Hentai / iQDB in parallel → Qwen3-VL extracts title/author/tags for forward search on JM; identical-image results are cached for instant replies |
| `@bot 识图` | 进入识图等待窗口：20 秒内直接发图即可搜（无需再@） | Enter image-search mode: send the image within 20 s (no re-mention needed) |
| `@bot 随机` | 从近 30 天最火的本子里随机推荐一本（优先章节少的） | Random pick from the hottest albums of the last 30 days (prefers fewer chapters) |
| `@bot 今日属性` | 占卜今日属性（NTR/纯爱等 36 个标签），@你并附赠一本（优先章节少的） | Daily "attribute" fortune (36 tags), mentions you and gifts a matching album (prefers fewer chapters) |
| `@bot 详情 <ID>` | 查看漫画详情（标题/作者/标签/章节页数，纯文字） | Show album details (title / author / tags / pages, text only) |
| `@bot 下载 <序号>` / `@bot 详情 <序号>` | 操作自己最近一次搜索、榜单或识图结果中的对应序号 | Download / preview an item from **your own** latest search, ranking, or image result |
| `@bot 任务` | 查看正在处理的任务及预计剩余时间 | Show in-progress tasks with ETA |
| `@bot 我的任务` / `@bot 我的下载` | 查看自己的排队任务或最近 10 条下载历史（重启后保留）；`@bot 重发 1` 重试对应记录 | Show your queued jobs or last 10 download records (survives restarts); `@bot 重发 1` retries an entry |
| `@bot 收藏 JM123456` / `收藏 3` | 收藏作品；也可对自己当前结果的序号收藏 | Save an album, or save an item by index from your own current results |
| `@bot 订阅作者 <名字>` / `订阅标签 <标签>` | 收藏作者/标签并按个人日报或周报接收聚合更新 | Subscribe to an author/tag and receive a per-user daily or weekly digest |
| `@bot 我的收藏` / `取消收藏 1` | 查看或删除自己的收藏/订阅；`订阅设置 每周` 调整节奏 | List/remove subscriptions; `订阅设置 每周` changes digest cadence |
| `@bot 管理 帮助` | 管理员诊断、暂停/恢复队列、取消任务与订阅检查（需 `JM_ADMIN_USERS`） | Admin diagnostics, queue control, task cancellation, subscription checks (requires `JM_ADMIN_USERS`) |
| `@bot 自查` | 查看机器人运行时长与当前 QQ 连接状态 | Show bot uptime and current QQ connection status |
| `@bot 安装包` | 发送禁漫天堂 APP 安装包（安卓 APK + 苹果描述文件，加密 ZIP 上传群文件 + 浏览器链接；也支持 `禁漫`/`禁漫天堂`/`禁漫安装包`/`天堂安装包`/`jm安装包`/`jm2安装包`/`jm3安装包`） | Send the official app installer (Android APK + iOS profile, encrypted ZIP + browser link; `禁漫`/`禁漫天堂`/`禁漫安装包`/`天堂安装包`/`jm安装包`/`jm2安装包`/`jm3安装包` also work) |
| `@bot 下一页` | 翻页；**直接发「下一页」「第N页」也可（无需@）** | Next page; **just send `下一页` / `第N页` (no mention needed)** |
| `@bot 不对` | 重新搜索上一次的结果（含识图重搜） | Re-run the last search (image search included) |
| `@bot 取消` | 取消**自己**最近的下载或排队任务，不影响其他群成员 | Cancel **your own** latest download or queued job; never affects another member |
| `@bot 说明` | 查看使用说明 | Show the help text |
| `@bot 菜单` / `@bot 按钮` | 返回按钮式命令面板（`@bot 菜单`/`@bot 按钮`/`@bot 面板`） | Show the button-style command panel |
| **免@按钮**（无需@） | 直接发「随机」「今日属性」「日榜」「周榜」「月榜」「安装包」「任务」「自查」「说明」即可触发对应功能，等同点按钮 | **Button words** (no mention needed): just send `随机` / `今日属性` / `日榜` / `周榜` / `月榜` / `安装包` / `任务` / `自查` / `说明` directly to trigger the same action |

## 任务状态与数据 Task state & data

- **结果隔离**：搜索、排行榜和识图结果都按 `群 + 用户` 保存；同一群内 A 的翻页、`下载 3` 不会影响 B。
- **公平队列**：全局默认同时下载 2 本；单个用户最多保有 2 个活跃任务（执行中或排队中），避免刷满队列。
- **可恢复历史**：任务元数据保存在本机 SQLite `data/jmniang.sqlite3`。机器人重启后，`我的下载` 仍可查看最近记录；若 ZIP 缓存尚在，`重发 N` 会优先直接发送缓存。
- **大文件与章节**：指定章节保存到独立缓存目录；超出 `JM_MAX_ZIP_PART_BYTES` 的交付文件会拆成多个**各自可解压**的 AES ZIP，而非不可用的字节切片。
- **订阅摘要**：第一次检查只建立基线，不将旧内容当成新更新；后续新作品先聚合，按用户设定的日报/周报发到原群。
- **最小化记录**：数据库只保存群号、用户号、JM ID、任务状态、标题、时间和本地缓存路径；不保存群聊正文、图片或任何凭据。`data/` 已在 `.gitignore` 中，绝不提交。

*Results are isolated by group and user; the global queue is fair; task history persists locally in SQLite and never stores message text, images, or credentials.*

## 效果示例 Demo

搜索关键词「枫与铃」（简体输入，自动匹配日文标题「楓と鈴」）：

> 🧑 `@JM娘 枫与铃`
>
> 🤖 🔍 关键词「枫与铃」（第 1/1 页 · 共 5 本）：
> 1. 《[きょくちょ] 楓と鈴 (全) [中國翻譯] [無修正] [DL版]》 章节：1章
>    🔢 ID：1235379
> …
> 💡 直接发「下一页」翻页，或发「第N页」跳转（无需@我）

今日属性（@原用户 + 随机标签 + 附赠本子）：

> 🧑 `@JM娘 今日属性`
>
> 🤖 @🧑 🎭 今日你的属性是【纯爱】！
> 📕 附赠一本「纯爱」本子：
> 《申鶴 純愛》
> ✍️ 作者：八可可 Barcoco  章节：1章
> 🔢 ID：1459505

以图搜本（发一张图 → OCR / 视觉模型识别 → 反查禁漫）：

> 🧑 [发送封面图片]
> 🤖 🔍 以图搜本：OCR 识别封面文字「楓と鈴」→ 禁漫匹配：
> 1. 《[きょくちょ] 楓と鈴 (全) [中國翻譯] [無修正] [DL版]》 章节：1章
>    🔢 ID：1235379
> 💡 没搜对？发「不对」重新搜

## 亮点 Highlights

- **智能中日文搜索 Smart CJK search** —— 简体输入自动匹配繁体 / 日文汉字 / 假名标题，四层降级：
  1. 简→繁转换（`zhconv`）
  2. 汉字异体映射（如 `琉→瑠`、`绘→絵`）
  3. 中文虚词→日文假名（如 `与/和→と`、`的/之→の`，搜「枫与铃」能命中「楓と鈴」）
  4. 核心字降级搜索：拆词逐字搜索、标题含全部核心字即命中（无字典依赖的普适兜底）

  *Searching with Simplified Chinese automatically matches Traditional / Japanese titles through a 4-layer fallback: (1) Simplified→Traditional via `zhconv`, (2) hanzi variant map (`琉→瑠`, `绘→絵`), (3) Chinese function words → kana (`与/和→と`, `的/之→の` — `枫与铃` finds `楓と鈴`), (4) dictionary-free core-character degraded search.*

- **搜索结果翻页/跳页 Pagination** —— 每页 5 本，直接发「下一页」或「第N页」翻页跳页（均无需 @机器人）。*5 per page; send `下一页` / `第N页` to page or jump, no mention needed.*

- **以图搜本 Reverse image search** —— OCR 文字优先 → SauceNAO / E-Hentai / iQDB 并行识图 → Qwen3-VL 结构化提取标题/作者/标签**正向搜禁漫**兜底；同一张图结果缓存秒回；视觉模型可配（默认免费 Qwen3-VL-8B，可配 Qwen3-VL-30B-A3B 更快更准）。*OCR text first → SauceNAO / E-Hentai / iQDB in parallel → Qwen3-VL extracts title/author/tags for forward search on JM; identical-image results cached; vision model configurable (free Qwen3-VL-8B default, Qwen3-VL-30B-A3B for speed & accuracy).*

- **加密 ZIP（AES-128）Encrypted ZIPs** —— QQ 上传会扫描 ZIP 内容并静默删除成人文件；加密使扫描失效（实测：未加密 `retcode=1200`，AES 加密 `retcode=0`）。*QQ scans ZIP contents on upload; encryption defeats it (verified: unencrypted `retcode=1200` → AES `retcode=0`).*

- **浏览器下载链接 Browser download links** —— 每次下载附带 HTTP 直链兜底。*Every download also gets an HTTP link as a fallback.*

- **CQ 码转义 CQ-code escaping** —— 用户可控字符串回显前转义，群成员无法用 `[CQ:...]` 让机器人 @全体 / 冒名发图。*User-controlled strings are escaped before being echoed, blocking `[CQ:...]` injection.*

- **每群限流 Rate limiting** —— 搜索类命令 10 秒冷却。*10 s per-group cooldown on search commands.*

- **稳定性保障 Stability** —— NapCat 看门狗每分钟检测、崩溃自动拉起（`-q` 快速登录免扫码，约 1-2 分钟恢复；10 分钟冷却）；升级窗口内 @机器人 自动回复"正在升级中"；被邀请进群自动同意并发欢迎消息。*Watchdog auto-recovery (~1-2 min: 1-min poll + `-q` quick login, 10-min cooldown); "upgrading" reply during deploys; auto-accepts group invites.*

- **下载体验 Download UX** —— 进度汇报（按完成百分比阈值触发、全程约 7 条不刷屏，上传按文件大小自适应）、排队时告知现有任务与预计时间、并发排队（2 本）、下载失败自动换 CDN 重试、24 小时自动清理。*Progress reports (percentage-threshold based, ~7 messages per download; upload interval adapts to file size), queue status with ETA, queueing (2 concurrent), auto CDN retry, 24-hour auto-cleanup.*

## 架构 Architecture

```
QQ group chat ── OneBot v11 (WebSocket) ──► NapCat ──► JM bot (Python, this repo)
                                                            │
                                            jmcomic ──► download album ──► AES ZIP
                                                            │
                              upload_group_file ──► QQ group files
                              publish token URL  ──► http.server :8080
                              task metadata      ──► SQLite (data/jmniang.sqlite3)
```

## 快速开始 Quick Start

```bash
# 1. 安装依赖 · install dependencies
pip install -r requirements.txt

# 2. 配置环境变量 · configure environment
export JM_ZIP_PASSWORD='你的ZIP密码'
export JM_PUBLIC_IP='你的服务器公网IP'

# 3. 启动 · run
python jm_niang.py
```

完整部署步骤（NapCat 配置、systemd 服务）见下方 [详细部署](#详细部署-deployment)。

See [Deployment](#详细部署-deployment) below for the full setup (NapCat config, systemd service).

## 详细部署 Deployment

### 1. 安装 NapCat 并配置 OneBot WebSocket

安装对应平台的 NapCat（见官方文档），用机器人 QQ 号扫码登录一次，然后在 NapCat 里新增一个 OneBot v11 **正向 WebSocket 服务端**，监听 `ws://127.0.0.1:8081`（机器人主动连它）。可选：调高 OneBot 配置里的上传限速（`uploadSpeedKBps`）。

Install NapCat for your platform (see official docs), log in with the bot's QQ account (scan the QR once), then create an OneBot v11 **forward WebSocket server** on `ws://127.0.0.1:8081`. Optionally raise `uploadSpeedKBps`.

**反检测配置（重要）**：QQ 会检测 NapCat 的注入特征并判定为"设备存外挂"强制下线。必须开启 NapCat 反检测开关——注意要改**账号级配置** `config/napcat_<QQ号>.json`（主配置 `napcat.json` 会被它覆盖；改完看启动日志 `[Core] [Config] 配置文件…加载` 确认生效）：

**Anti-detection config (important)**: QQ detects NapCat's injected hooks and force-logs-out the device as "plugin abuse". You must enable NapCat's bypass flags — in the **per-account config** `config/napcat_<uin>.json` (the main `napcat.json` is overridden by it; verify via the startup log line `[Core] [Config] 配置文件…加载`):

```json
{
  "o3HookMode": 1,
  "bypass": {
    "hook": true, "window": true, "module": true,
    "process": true, "container": true, "js": true
  }
}
```

### 2. 配置机器人 Configure

敏感值通过**环境变量**读取（不写死在代码里），参考 [`.env.example`](.env.example)。

Sensitive values are read from environment variables (never hard-coded); see [`.env.example`](.env.example).

用 HTTP 服务托管下载目录（8080 端口）。Serve the download directory over HTTP on port 8080:

```bash
mkdir -p http_dl
python3 -m http.server 8080 --bind 0.0.0.0 --directory http_dl
```

### 3. 运行 Run

```bash
python jm_niang.py
```

或使用 systemd 服务（推荐）。Or as a systemd service (recommended):

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

### 4. 可选：群白名单（Optional: allow-list groups）

编辑 `jm_niang.py` 里的 `ALLOWED_GROUPS` 可限制使用机器人的群（空列表 = 所有群可用）。

Edit `ALLOWED_GROUPS` in `jm_niang.py` to restrict which groups may use the bot (empty = all groups).

## 配置 Configuration

| 变量 Variable | 必填 Required | 含义 Meaning |
|---|---|---|
| `JM_ZIP_PASSWORD` | ✅ | 上传 ZIP 的 AES 密码（需告知用户）。AES password for uploaded ZIPs. |
| `JM_PUBLIC_IP` | ✅ | 服务器公网 IP/域名，用于生成浏览器下载链接。Public IP/host used to build download links. |
| `JM_PROXY` | ❌ | 可选 HTTP 代理（如 `http://127.0.0.1:7890`；留空 = 直连）。Optional HTTP proxy (empty = direct). |
| `JM_SAUCENAO_KEY` | ❌ | SauceNAO 识图 API key（免费注册 https://saucenao.com/user.php；未填时以图搜本仅用 iQDB 兜底）。Optional SauceNAO API key for reverse image search (free; without it only iQDB is used). |
| `JM_LLM_KEY` | ❌ | 视觉大模型 API key（SiliconFlow，免费注册 https://siliconflow.cn；未填时以图搜本无内页 AI 识别层；已填时还可结构化提取标题/作者/标签正向搜禁漫）。Optional vision LLM API key (SiliconFlow; without it inner-page AI recognition is skipped; with it the bot can also extract title/author/tags for forward search on JM). |
| `JM_GOOGLE_KEY` | ❌ | Google Cloud Vision API key（Web Detection 识图，每月前 1000 次免费，但需绑定海外信用卡启用；未填时该层自动跳过）。Optional Google Vision API key (1,000 free calls/month, but requires an international credit card to enable billing; skipped if empty). |
| `JM_EH_COOKIES` | ❌ | E-Hentai 登录 cookie（以图搜本，登录 e-hentai.org 后 F12 控制台 `document.cookie` 复制整串；未填时 EH 识图层跳过）。Optional E-Hentai login cookie for reverse image search (run `document.cookie` in F12 console after login; skipped if empty). |
| `JM_LLM_MODEL` | ❌ | 识图视觉模型（可选；默认 Qwen/Qwen3-VL-8B-Instruct 免费档；付费可配 Qwen/Qwen3-VL-30B-A3B-Instruct，更快更准）。Optional vision model for image search (default free Qwen/Qwen3-VL-8B-Instruct; paid Qwen/Qwen3-VL-30B-A3B-Instruct is faster & better). |
| `JM_AGENTKEY_KEY` | ❌ | AgentKey API key（https://console.agentkey.app/ 获取；ascii2d 直连被反爬时自动经 AgentKey/Firecrawl 浏览器渲染中转，绕过数据中心 IP 封锁）。Optional AgentKey API key; when ascii2d direct access is blocked, the bot falls back to an AgentKey/Firecrawl browser-rendered relay that bypasses datacenter-IP blocks. |
| `JM_NEW_IMAGE_SOURCES` | ❌ | 启用 ascii2d / Yandex 新识图源（默认空=关；ascii2d 直连被反爬时自动经 AgentKey/Firecrawl 中转，配 `JM_AGENTKEY_KEY` 即可生效；Yandex 仍需代理）。Enable ascii2d/Yandex sources (empty=off; ascii2d falls back to AgentKey/Firecrawl relay when blocked — just set `JM_AGENTKEY_KEY`; Yandex still needs a proxy). |
| `JM_MAX_ZIP_PART_BYTES` | ❌ | 每个可独立解压 ZIP 分卷的最大字节数；默认 900MiB，设 `0` 关闭自动分卷。Maximum bytes per independently extractable ZIP part; default 900MiB, `0` disables splitting. |
| `JM_ADMIN_USERS` | ❌ | 可使用管理命令的 QQ 号，英文逗号分隔；默认空，安全地禁用管理入口。Admin QQ IDs, comma-separated; empty safely disables admin commands. |
| `JM_SUBSCRIPTION_CHECK_SECONDS` | ❌ | 订阅检查间隔秒数（默认 3600）；真正发送仍按用户日报/周报。Subscription polling interval (default 3600); actual delivery still follows daily/weekly cadence. |

## 运维 Operations

### 看门狗与自动恢复 Watchdog & auto-recovery

仓库自带两个运维脚本（已在生产环境跑通），保障机器人"掉线了也能自己爬起来"：

```bash
# napcat_watchdog.sh —— 每分钟检测 NapCat 8081 端口，掉线自动拉起 QQ（快速登录，已登录态免扫码）
# 由 cron 每分钟执行；脚本内置 10 分钟冷却，防止反复重启风暴（注意：冷却期内再崩不会拉起）
# ⚠️ 检测用 /usr/sbin/ss 绝对路径——用户 crontab 默认 PATH 不含 /usr/sbin，用裸 ss 会一直误判掉线并误杀 QQ
* * * * * /opt/jmniang/napcat_watchdog.sh
```

> 💡 **原理（懂行版）**：QQ Linux 客户端会周期性崩溃（此前误以为间隔 30→20→10 分钟恶化——**真相是 watchdog 误杀**：v4/v5 用裸 `ss` 检测，用户 crontab PATH 不含 /usr/sbin 导致永远误判掉线、冷却结束就杀 QQ，周期数=冷却时间变化；v6 改 `/usr/sbin/ss` 绝对路径后已修复）。另有腾讯风控因素（详见 [docs/qq-crash-issue.md](docs/qq-crash-issue.md)）。watchdog 每 1 分钟检测 8081，掉线用 `-q <QQ号>` 快速登录拉起（token 有效即免扫码，拉起约 15-30 秒；10 分钟冷却期内不重复拉起）。
>
> 💡 *How it works: the Linux QQ client crashes periodically (the previously assumed 30→20→10-min worsening was actually the watchdog killing QQ: v4/v5 used bare `ss` which is absent from the user crontab PATH, so every check misdetected "down" and killed QQ once the cooldown lapsed; v6 uses the absolute path `/usr/sbin/ss` and fixes this). Tencent risk-control is also a factor (see [docs/qq-crash-issue.md](docs/qq-crash-issue.md)). The watchdog polls port 8081 every minute, then relaunches QQ with the `-q <uin>` quick-login flag (token-based, no QR re-scan, ~15-30 s to come up; no relaunch within the 10-min cooldown).*

### 无感部署 Zero-downtime deploys

更新代码时用 `deploy.py`，整个升级过程对群友无感——升级窗口内 @机器人 会收到"正在升级中，请稍后"（由 `maintain_reply.py` 维护应答器代答）：

```bash
# 用法：python deploy.py <文件名>（远程路径内置映射）
# 前置：仓库根目录放 .deploy_secret 文件（服务器 root 密码，已被 .gitignore 排除不入库）
python deploy.py jm_niang.py
```

> 💡 **原理（懂行版）**：`deploy.py` 按序执行：① 拉起 `maintain_reply.py`（另开一条 WS 连接独占 8081，回复所有 @ 消息"正在升级中"）→ ② `systemctl stop jmniang` → ③ base64 分块上传（服务器 sshd 对 SFTP 通道不稳定，改走 exec 通道 + md5 校验）→ ④ `systemctl start jmniang` → ⑤ 关闭应答器。任何一步失败会自动恢复 JM娘 并清理应答器。
>
> 💡 *The deploy script: (1) starts `maintain_reply.py`, a second WS client that answers all @mentions with "upgrading…" while the bot is down, (2) stops the bot, (3) uploads via chunked base64 over exec (the server's SFTP channel is flaky; md5-verified), (4) restarts the bot, (5) kills the replier. Any failure auto-restores the bot.*

## 测试 Tests

```bash
python -m pytest test_jm_download.py
```

当前 **40 项全绿**（需 `JM_ZIP_PASSWORD` 环境变量）。覆盖：ZIP 加密与独立分卷、CQ 转义、搜索变体、章节命令、个人结果隔离、SQLite 任务/订阅历史、识图置信度与深度复核、取消等（全部离线，无需联网）。 · **40 tests, all green** (requires `JM_ZIP_PASSWORD`). Covers ZIP encryption and independent parts, CQ escaping, search variants, chapter commands, per-user state, SQLite task/subscription history, image confidence/deep review and cancellation (offline).

Covers ZIP encryption, CQ escaping, search-variant generation, author command parsing, pagination/jump rendering and message-layer command routing (all offline).

## 排障 Troubleshooting

| 症状 Symptom | 原因与处理 Cause / fix |
|---|---|
| 机器人在群里没有反应 | QQ 账号被踢下线（NapCat 进程还活着）。探针：WS 调 `send_group_msg`，返回 `retcode=1200 ... NodeIKernelMsgService` 超时 = QQ 内核已死 → 重启 NapCat 并重新扫码 |
| Bot is silent in the group | The QQ account was kicked offline (NapCat stays alive). Probe via `send_group_msg`: `retcode=1200 ... NodeIKernelMsgService` timeout means the QQ kernel is dead → restart NapCat and re-scan QR |
| 群文件上传失败 | QQ 扫描 ZIP 内容并拒绝成人图片 → 保持 `ZIP_ENCRYPT = True`（AES-128）；用户需 WinRAR / 7-Zip / ZArchiver 解压 |
| Group file upload fails | QQ scans ZIP contents and rejects adult images → keep `ZIP_ENCRYPT = True` (AES-128); users need WinRAR / 7-Zip / ZArchiver |
| 明明存在的本子搜不到 | 站内搜索是精确子串匹配；4 层降级已覆盖简体/繁体/日文写法，但超冷门单字组合仍可能漏（见 `_search_by_core_chars`） |
| Search misses a known title | Site search is exact substring matching; the 4-layer fallback covers most cases, but ultra-rare combos may still miss (see `_search_by_core_chars`) |
| 机器人周期性掉线（间隔曾 30→20→10 分钟递减） | **已查明：watchdog v4/v5 误杀**——裸 `ss` 在用户 crontab PATH 中不存在 → 永远误判 8081 down → 冷却结束就杀 QQ（周期数=冷却时间变化）；v6 改用 `/usr/sbin/ss` 绝对路径修复。真掉线另有：腾讯风控踢号（反检测 bypass 已开启应对）。详见 [docs/qq-crash-issue.md](docs/qq-crash-issue.md) |
| Bot drops offline periodically (intervals shrank 30→20→10 min) | **Root cause found: watchdog v4/v5 killed QQ by mistake** — bare `ss` is not in the user-crontab PATH, so every check misdetected 8081 as down and killed QQ once the cooldown lapsed; v6 uses `/usr/sbin/ss` and fixes it. Real drop-offs also come from Tencent risk-control (anti-detection bypass enabled). See [docs/qq-crash-issue.md](docs/qq-crash-issue.md) |
| 群里出现两个同名文件 | 已修复：上传失败重试前会查群文件列表去重，列表 API 异常时停止重试（重试上限 2 次） |
| Duplicate files appear in group | Fixed: the uploader checks the group file list before retrying, and stops retrying if the list API is broken (max 2 attempts) |

## 常见问题 FAQ

**Q：下载的 ZIP 解压要密码，密码是什么？**
A：是部署时配置的 `JM_ZIP_PASSWORD`。必须加密——QQ 会扫描 ZIP 内容并静默删除成人图片（实测未加密 `retcode=1200` 上传失败，AES-128 加密后 `retcode=0` 正常）。用 WinRAR / 7-Zip / ZArchiver 解压即可。

**Q：为什么机器人偶尔掉线？**
A：曾查出两大原因：① watchdog v4/v5 误杀（裸 `ss` 不在 crontab PATH → 误判掉线 → 冷却结束杀 QQ；v6 已修复）；② 腾讯风控踢号（已开反检测 bypass 应对）。真正的掉线极少，机器人会 `-q` 快速登录自动恢复（约 1-2 分钟）。

**Q：掉线期间发的命令会丢失吗？**
A：会。QQ 重登后不补推离线消息（掉线期间的消息已被手机端接收），所以掉线窗口内的 @ 命令机器人收不到，上线后请重新发一次。

**Q：升级机器人时群里会怎样？**
A：升级窗口内 @机器人 会收到"🚧 正在升级中，请稍后～"；窗口通常只有几秒钟。

**Q：怎么让机器人进我的群？**
A：在群里邀请机器人 QQ 号即可——它会自动同意邀请并进群发欢迎消息（QQ 协议限制机器人不能主动加群）。

*Q: What's the ZIP password? — A: The `JM_ZIP_PASSWORD` you configured at deploy time. Encryption is mandatory because QQ silently deletes adult images inside plain ZIPs (verified: unencrypted upload fails with `retcode=1200`; AES-128 passes with `retcode=0`). Unzip with WinRAR / 7-Zip / ZArchiver.*

*Q: Why does the bot drop offline sometimes? — A: Two root causes were found: (1) watchdog v4/v5 killed QQ by mistake (bare `ss` absent from the crontab PATH → false "down" detection → QQ killed once the cooldown lapsed; fixed in v6); (2) Tencent risk-control kick (anti-detection bypass enabled). Real drop-offs are rare now; the watchdog restores the bot in ~1-2 min (`-q` quick login).*

*Q: Do commands sent while offline get lost? — A: Yes. QQ does not re-push offline messages (they are already consumed by the phone client), so @commands sent during an outage never reach the bot. Please resend them after it comes back.*

*Q: What happens during bot upgrades? — A: @mentions during the deploy window get "🚧 Upgrading, please wait"; the window is usually a few seconds.*

*Q: How do I get the bot into my group? — A: Just invite the bot's QQ account; it auto-accepts invites and greets the group (QQ protocol forbids bots from joining groups on their own).*

## 项目结构 Project layout

```
jm_niang.py          # QQ 机器人主循环：OneBot WS 客户端、命令处理、上传、翻页/跳页、自动同意邀请
                     # QQ bot main loop: OneBot WS client, command handling, uploads, pagination, auto-accept invites
jm_download.py       # jmcomic 封装：整本/指定章节→AES ZIP/独立分卷、智能搜索、以图搜本（含深度裁图复核）
                     # jmcomic wrapper: download → AES ZIP, smart CJK search, image search (OCR→engines→LLM forward search + cache)
jm_store.py          # SQLite：个人任务/下载历史、订阅基线/摘要、取消与公平队列计数（不存消息正文或凭据）
                     # SQLite task store: personal task/history, cancellation and fair-queue counts (no message bodies or secrets)
maintain_reply.py    # 维护应答器：升级窗口内代答"正在升级中"（deploy.py 自动拉起/关闭）
                     # maintenance replier: answers @mentions with "upgrading" during deploy windows
deploy.py            # 无感部署脚本：应答器→停机→上传→恢复→清理，失败自动回滚
                     # zero-downtime deploy script: replier → stop → upload → restore → cleanup, auto-rollback on failure
napcat_watchdog.sh   # NapCat 看门狗：每分钟检测 8081，掉线自动拉起 QQ（快速登录免扫码；用 /usr/sbin/ss 绝对路径）
                     # NapCat watchdog: polls port 8081 every minute, relaunches QQ on crash (absolute /usr/sbin/ss path)
qq_official_bot.py   # 官方机器人接入（已停用备用）：真·按钮需官方机器人，群权限卡点后放弃，代码保留
                     # official bot integration (disabled, kept for reference): real buttons need official bot; dropped after group-permission blocker
test_jm_download.py  # 离线单元测试（40 项全绿）· offline unit tests (40 green)
test_qq_official_bot.py # 官方机器人单元测试 · official-bot unit tests
requirements.txt     # 依赖清单 · dependency list
docs/qq-crash-issue.md # 掉线/崩溃问题完整技术档案（真相大白归档）· full crash/outage investigation archive
.env.example         # 环境变量示例 · environment variable template
start_jmniang.bat    # 可选 Windows 启动脚本 · optional Windows launcher
```

## 更新日志 Changelog

| 日期 Date | 里程碑 Milestone |
|---|---|
| 08-13 | 初版：下载→加密 ZIP→群文件+链接；四层智能搜索、翻页/跳页、作者/标签/榜单、随机、今日属性、以图搜本（OCR→SauceNAO/iQDB→Qwen3-VL） |
| 08-14 | 稳定性攻坚：watchdog 误杀真相（`ss` PATH 坑，v6 修复）、反检测 bypass、无感部署、自动同意邀请 |
| 08-15 | 腾讯弱密码爆破实锤 → ZIP 密码 `jm321`；安装包功能（安卓+苹果）；缓存 24h 清理 |
| 08-17 | 免@按钮菜单；官方机器人真按钮路线尝试（被群权限卡点，放弃，代码保留） |
| 08-19 | 取消/下载竞态修复；进度条改百分比阈值（全程约 7 条不刷屏） |
| 08-20 | 识图 ascii2d+Yandex 新源（代码保留；服务器 DC IP 反爬，配代理后可启用） |
| 08-21 | 识图增强：LLM 结构化正向搜索 + 图片结果缓存 + OCR 水印过滤 + 视觉模型可配（Qwen3-VL-30B-A3B） |
| 08-22 | 个人状态底座：搜索/识图结果按群成员隔离；SQLite 任务历史、缓存重发、个人取消与单用户公平队列上线 |
| 08-22 | 路线 7.2–7.5：指定章节、独立 AES 分卷、识图置信度/深度复核、收藏订阅摘要、管理员队列与诊断上线 |

*Initial release (08-13): download → AES ZIP → group files + link; 4-layer CJK search, pagination, author/tag/ranking, random, fortune, image search (OCR→SauceNAO/iQDB→Qwen3-VL). Stability (08-14): watchdog v6 fix, anti-detection, zero-downtime deploys, auto-accept invites. (08-15): weak-password brute-force found → `jm321`; installer feature. (08-17): mention-free button menu; official-bot buttons dropped. (08-19): cancel race fixes; percentage-threshold progress. (08-20): ascii2d/Yandex sources kept in code (datacenter IP blocked, enable with proxy). (08-21): LLM structured forward search + image cache + OCR watermark filter + configurable vision model (Qwen3-VL-30B-A3B).*

## License

[MIT](LICENSE) © 2026 spdw666
