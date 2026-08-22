<div align="center">

# 🤖 JM娘

**基于 OneBot v11 / NapCat 的 QQ 群机器人：搜索、识图、下载、订阅与运维自查。**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![OneBot](https://img.shields.io/badge/Protocol-OneBot%20v11-7d3cff?style=flat-square)](https://onebot.dev/)
[![jmcomic](https://img.shields.io/badge/jmcomic-2.7.4-ff69b4?style=flat-square)](https://github.com/tonquer/jmcomic)
[![Tests](https://img.shields.io/badge/tests-40%20passed-brightgreen?style=flat-square)](test_jm_download.py)
[![License](https://img.shields.io/badge/License-MIT-2ea44f?style=flat-square)](LICENSE)

[快速开始](#快速开始) · [命令速查](#命令速查) · [部署](#生产部署) · [配置](#配置) · [运维](#运维) · [路线图](docs/roadmap.md)

</div>

> 本项目仅供学习与交流。使用者须自行遵守所在地法律、内容平台与 QQ/NapCat 的服务条款；自动化客户端可能触发账号风控。

## 这是什么

JM娘将群内请求转为受控下载任务：查询结果按用户隔离，下载以 AES ZIP 交付，并给出群文件和浏览器链接两条路径。它把“查找、下载、复用缓存、订阅更新、管理员诊断”放在同一个群机器人中。

| 能力 | 设计要点 |
|---|---|
| 搜索与发现 | 关键词、作者、标签、榜单、随机推荐；简繁/日文变体与分页。 |
| 下载交付 | 整本、指定章节、最新章节；AES ZIP、可独立解压的自动分卷、HTTP 直链兜底。 |
| 图片识别 | OCR、识图源和视觉模型协作；候选置信度；“都不对”触发中心裁图深度复核。 |
| 个人状态 | 结果、任务、下载历史、收藏和订阅均按“群 + 用户”隔离并持久化。 |
| 群内治理 | 公平队列、个人取消、管理员诊断、暂停/恢复队列、订阅摘要。 |

## 命令速查

默认使用方式是 `@JM娘 <命令>`。只 @ 机器人会返回菜单；标为“免 @”的词可直接发送。

### 搜索与下载

| 命令 | 作用 |
|---|---|
| `<JM ID>` / `/jm<JM ID>` | 下载整本。 |
| `下载 JM123456 第2-5章` | 下载连续指定章节，单次最多 50 章。 |
| `下载 JM123456 最新` | 下载最后一章。 |
| `<关键词>` / `作者 <名字>` / `标签 <标签>` | 搜索作品、作者或标签。 |
| `日榜` / `周榜` / `月榜` | 查看排行榜。 |
| `下一页` / `第3页` | 翻页或跳页；可免 @。 |
| `下载 3` / `详情 3` | 操作**你自己的**最近搜索、榜单或识图结果中的第 3 条。 |
| `详情 <JM ID>` | 查看标题、作者、标签和章节页数。 |
| `取消` | 取消**自己**最近的排队或执行任务，不影响其他成员。 |

下载完成后，若 ZIP 超过 `JM_MAX_ZIP_PART_BYTES`，机器人会生成多个**各自可解压**的 AES ZIP；不是需要手动拼接的字节切片。

### 识图、历史与订阅

| 命令 | 作用 |
|---|---|
| `识图` 后在 20 秒内发图，或直接 @机器人并发图 | 识别图片并在禁漫匹配候选。 |
| `都不对` | 绕过图片缓存，对中心裁图再次识别并合并候选。 |
| `我的任务` / `我的下载` | 查看自己的活跃任务或最近下载记录。 |
| `重发 1` | 重新处理第 1 条下载记录，优先复用服务器缓存。 |
| `收藏 JM123456` / `收藏 3` | 收藏作品或当前结果中的作品。 |
| `订阅作者 <名字>` / `订阅标签 <标签>` | 创建作者或标签订阅。 |
| `我的收藏` / `取消收藏 1` | 管理自己的收藏和订阅。 |
| `订阅设置 每日` / `订阅设置 每周` | 调整个人订阅摘要节奏。 |

订阅第一次检查只建立基线，历史作品不会被误推送；之后新内容会先聚合，再按个人日报或周报发送到原群。

### 免 @ 与管理员命令

| 命令 | 作用 |
|---|---|
| `随机`、`今日属性`、`日榜`、`周榜`、`月榜`、`安装包`、`任务`、`自查`、`说明` | 免 @ 快捷词。 |
| `自查` | 一次汇总进程、NapCat/QQ、DNS、下载队列、磁盘、识图链路、缓存与 SQLite 状态；不显示凭据。 |
| `管理 帮助` | 管理入口；需要请求者 QQ 号配置在 `JM_ADMIN_USERS`。 |
| `管理 状态` / `管理 任务` | 查看队列、磁盘、任务和订阅诊断。 |
| `管理 暂停队列` / `管理 恢复队列` | 控制未开始任务；不会中断正在下载或上传的任务。 |
| `管理 取消 <任务ID前6位>` | 取消唯一匹配的活跃任务。 |
| `管理 检查订阅` / `管理 发送订阅摘要` | 手动检查订阅或触发汇总。 |

## 状态、队列与数据边界

```text
群成员 ──► 搜索/识图结果（群 + 用户，10 分钟）
     └──► 下载任务（SQLite，群 + 用户） ──► 全局下载队列（默认 2 并发）
                                                └──► AES ZIP / 分卷 / 群文件 / HTTP 链接
订阅 ──► SQLite 基线与待发摘要 ──► 日报或周报
```

- 单个用户最多保有 2 个活跃任务（执行中或排队中），避免占满全局槽位。
- 任务、下载历史和订阅保存在 `data/jmniang.sqlite3`；重启后仍可查询。
- 章节缓存位于 `downloads/partials/`，与整本缓存隔离。
- 数据库只保存群号、用户号、JM ID、状态、标题、时间、缓存路径和订阅元数据；不保存聊天正文、图片、密码、密钥或 Cookie。
- `data/`、下载内容、日志和本地密钥文件均已在 `.gitignore` 中排除。

## 架构

```text
QQ 群 ── OneBot v11 ── NapCat ── jm_niang.py
                                      ├─ jm_download.py ── jmcomic / 识图源 / 视觉模型
                                      ├─ jm_store.py ── SQLite（任务、历史、订阅）
                                      ├─ AES ZIP / 独立分卷 ── 群文件 + HTTP 分享目录
                                      └─ 自查、管理员命令、订阅后台任务
```

## 快速开始

```bash
git clone https://github.com/spdw666/Create-a-QQ-bot-and-add-it-to-the-group-chat-to-easily-search-for-JM-doujinshi.git
cd Create-a-QQ-bot-and-add-it-to-the-group-chat-to-easily-search-for-JM-doujinshi
python -m pip install -r requirements.txt

# 仅示例：生产环境请通过 systemd Environment= 或安全的环境管理方式配置。
export JM_ZIP_PASSWORD='change-this'
export JM_PUBLIC_IP='your-public-host'
python jm_niang.py
```

还需要在 NapCat 中创建**正向 WebSocket 服务端**，监听 `ws://127.0.0.1:8081`。机器人主动连接此地址。

## 生产部署

### 1. 配置 NapCat

安装与登录步骤以 [NapCat 文档](https://napneko.github.io/) 为准。账号级配置与反检测选项应遵循其当前文档；不要把 QQ 密码、登录 token 或二维码提交到仓库。

### 2. 创建 systemd 服务

```ini
# /etc/systemd/system/jmniang.service
[Unit]
Description=JM Niang QQ Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/jmniang
Environment="JM_ZIP_PASSWORD=replace-me"
Environment="JM_PUBLIC_IP=your-public-host"
ExecStart=/usr/bin/python3 -u /opt/jmniang/jm_niang.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now jmniang
sudo systemctl status jmniang
```

以独立 drop-in 启用管理员，避免改写主服务文件：

```ini
# /etc/systemd/system/jmniang.service.d/20-admin.conf
[Service]
Environment="JM_ADMIN_USERS=123456789,987654321"
```

### 3. 启动 HTTP 分享服务

```bash
mkdir -p /opt/jmniang/http_dl
python3 -m http.server 8080 --bind 0.0.0.0 --directory /opt/jmniang/http_dl
```

生产环境建议把该命令也封装为 systemd 服务，并仅在防火墙中开放必要端口。

## 配置

完整示例见 [`.env.example`](.env.example)。敏感值只通过环境变量或服务管理器注入，绝不写进代码、README 或 Git。

### 核心配置

| 变量 | 是否必填 | 说明 |
|---|---:|---|
| `JM_ZIP_PASSWORD` | 是 | AES ZIP 密码；需要通过可信渠道告知解压用户。 |
| `JM_PUBLIC_IP` | 是 | 生成浏览器下载链接的公网 IP 或域名。 |
| `JM_PROXY` | 否 | jmcomic 和部分识图源使用的 HTTP 代理。 |
| `JM_MAX_ZIP_PART_BYTES` | 否 | 单个独立 ZIP 分卷最大字节数；默认 900 MiB，`0` 关闭分卷。 |
| `JM_ADMIN_USERS` | 否 | 管理员 QQ 号，英文逗号分隔；默认空，管理命令安全禁用。 |
| `JM_SUBSCRIPTION_CHECK_SECONDS` | 否 | 订阅检查间隔，默认 3600 秒；实际发送仍按日报/周报。 |

### 识图配置

| 变量 | 用途 |
|---|---|
| `JM_SAUCENAO_KEY` | 启用 SauceNAO。未配置时使用其他可用识图路径。 |
| `JM_LLM_KEY` / `JM_LLM_MODEL` | 启用视觉模型的标题、作者、标签结构化提取。 |
| `JM_GOOGLE_KEY` | 启用 Google Vision Web Detection。 |
| `JM_EH_COOKIES` | 启用 E-Hentai 识图层；Cookie 仅存服务器环境。 |
| `JM_AGENTKEY_KEY` | ascii2d 直连被拦截时，启用 AgentKey/Firecrawl 中转。 |
| `JM_AGENTKEY_DAILY_LIMIT` | AgentKey 中转的每日调用上限；默认 `50`。 |
| `JM_NEW_IMAGE_SOURCES` | 设为非空以启用 ascii2d / Yandex 新源。 |

## 运维

### 日常检查

群内直接发送 `自查`。报告包含 NapCat 连接、DNS、下载队列、磁盘、识图能力、缓存、任务与订阅统计，并且不会回显任何敏感配置。

### NapCat 看门狗

```cron
# 每分钟检查 8081；脚本内置冷却，避免重复拉起。
* * * * * /opt/jmniang/napcat_watchdog.sh
```

脚本使用 `/usr/sbin/ss` 绝对路径，避免 cron 的 PATH 缺失导致误判。

### 无感部署

`deploy.py` 会启动维护应答器、停止机器人、校验上传、恢复服务并清理应答器：

```bash
# .deploy_secret 只保存在本机，已被 .gitignore 排除。
python deploy.py jm_niang.py
python deploy.py jm_download.py
python deploy.py jm_store.py
```

## 测试

```bash
python -m pytest -q
```

当前离线测试覆盖 ZIP 加密与独立分卷、命令解析、用户状态隔离、SQLite 任务/订阅、识图置信度与深度复核、取消与主要消息路由。测试不需要真实下载内容或外部账户。

## 常见问题

| 现象 | 检查顺序 |
|---|---|
| 群里无响应 | 先发 `自查`；确认 NapCat 已连接、8081 可达，再检查 QQ 登录状态。 |
| 群文件上传失败 | 确认 ZIP 加密开启；使用机器人给出的 HTTP 链接兜底。 |
| 搜索结果不准确 | 使用更完整的标题、作者或标签；结果页可用 `详情 N` 验证。 |
| 识图没有匹配 | 使用原图或包含标题的页面；发送 `都不对` 做深度复核。 |
| 订阅没有立即通知 | 首次只建基线；后续按个人日报/周报汇总。可由管理员执行订阅检查。 |
| 管理命令提示无权限 | 将请求者 QQ 号加入 `JM_ADMIN_USERS` 后执行 `systemctl daemon-reload && systemctl restart jmniang`。 |

## 项目结构

```text
jm_niang.py           OneBot 消息路由、队列、上传、订阅与运维命令
jm_download.py        jmcomic 下载、章节、AES ZIP、分卷、搜索和识图
jm_store.py           SQLite 任务、历史、收藏与订阅存储
deploy.py             带维护应答器和校验的部署脚本
maintain_reply.py     升级窗口的临时应答器
napcat_watchdog.sh    NapCat 端口看门狗
test_jm_download.py   离线单元测试
.env.example          环境变量样例
docs/                 路线图与故障档案
```

## 文档与变更

- [产品路线图](docs/roadmap.md)
- [NapCat/QQ 故障档案](docs/qq-crash-issue.md)

| 日期 | 变更 |
|---|---|
| 2026-08 | 完成个人任务、指定章节、独立 ZIP 分卷、识图深度复核、订阅摘要与管理员诊断。 |
| 2026-08 | 整理综合自查与部署流程；公开文档不再记录任何真实凭据。 |

## License

[MIT](LICENSE) © 2026 spdw666
