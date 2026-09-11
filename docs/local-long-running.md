# 本地电脑长期运行

适用于将云服务器上的 JM娘迁到一台长期在线的 Windows 电脑。机器人本体、SQLite 数据和下载缓存都保存在项目目录；QQ/NapCat 需要在该电脑的桌面会话中保持登录。

## 首次准备

1. 按 [Windows 新电脑首次运行](first-run.md) 安装依赖、创建 `.env`，并完成 NapCat 的 QQ 登录。
2. 确认 NapCat 配置为 **OneBot v11 正向 WebSocket 服务端**，地址 `127.0.0.1`、端口 `8081`。
3. 在机器人可用后，于群内发送 `自查`。报告中的 NapCat、队列、磁盘、缓存与 SQLite 项应正常。

JM娘会对这条本机回环 WebSocket 连接强制绕过系统代理；即使电脑配置了 HTTP/HTTPS 代理，也不会把 NapCat 流量转发到代理服务器。

本地 OCR 是可选增强。若首次网络下载失败，先启动核心机器人；待网络稳定后执行 `scripts/install_ocr.ps1`，再重启即可启用 OCR。

## 开机后自动运行

首次配置完成后，在项目根目录 PowerShell 执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install_autostart.ps1
```

它会为**当前 Windows 用户**在“登录后启动”目录创建一个快捷方式，不需要管理员权限。后台守护进程会：

- 以 `.venv` 中的固定 Python 启动 `run_jmniang.py`；
- 托管 `http_dl/` 的 HTTP 分享目录；
- 在程序异常退出后等待 10 秒自动重启；
- 在 NapCat 尚未启动时保持重连，不会因启动顺序而退出；
- 将启动和错误输出写入 `logs/jmniang-local.log`。

NapCat/QQ 本身也必须设置为登录后自动启动；否则 JM娘 会运行但一直等待本机的 8081 端口。关闭 Windows、注销当前用户或让电脑休眠都会中断服务。

取消登录自启动：

```powershell
.\scripts\remove_autostart.ps1
```

## 数据迁移说明

旧云服务器不可访问时，可以直接在本地新建 SQLite 数据库，机器人功能不会受影响；但旧的下载历史、收藏、订阅基线和缓存不会自动恢复。若云厂商在保留期内恢复了旧磁盘，可在机器人停止时复制以下目录到本地项目根目录后再启动：

```text
data/       # SQLite：任务、历史、收藏、订阅
downloads/  # 下载与章节缓存（可选）
http_dl/    # 临时分享文件（通常不建议迁移）
```

不要迁移 `.env`、QQ/NapCat 登录 token、Cookie 或旧服务器上的任何凭据；请在本地重新生成或重新登录。

## 网络边界

群文件上传可在普通家庭网络中使用。机器人给出的 HTTP 下载链接则要求群成员能访问本机：配置 `JM_PUBLIC_IP` 为公网 IP/域名，并放行 `JM_HTTP_PORT`（默认 8080）；或使用受控的反向代理/隧道。没有这项网络条件时，保留 `127.0.0.1` 即可，机器人仍可运行，只是 HTTP 链接不对其他群成员可用。
