# QQ 客户端周期性崩溃问题追踪（Crash Investigation）

> 状态：**真相大白——"周期崩溃"实为 watchdog 误杀假象，v6 已修复；真掉线仅剩腾讯风控（反检测已开启）** · Status: mystery solved — the "periodic crashes" were watchdog miskills, fixed in v6; only Tencent risk-control kicks remain (anti-detection bypass enabled)
> 相关 Issue：[本仓库 #1](../../issues/1)、[NapCat 官方 #2013](https://github.com/NapNeko/NapCatQQ/issues/2013)

## 最终结论 Conclusion（2026-08-14 20:20）

**下午"QQ 崩溃周期 30→20→10 分钟不断恶化"是一场乌龙**：watchdog v2-v5 用裸 `ss` 命令检测 8081 端口，而用户 crontab 的默认 PATH（`/usr/bin:/bin`）不含 `/usr/sbin`（`ss` 所在目录）→ 检测命令每次"command not found"→ 永远误判"8081 down"→ 冷却时间一结束就 `pkill` QQ 并重启。**周期数字 30→20→10 分钟 = watchdog 冷却时间的三次调整记录**，与 QQ 本身无关（跨版本 3.2.30/3.2.32 都"崩"也因此解释通）。

- 修复：watchdog v6 改用 `/usr/sbin/ss` 绝对路径。验证：cron 环境实测 QQ 不被误杀（PID 不变）、v6 部署后 watchdog 零误报、QQ 存活突破 10 分钟周期。
- 真实掉线仅剩：腾讯风控踢号（18:41 风险设备通知实锤；反检测 bypass 六项已开启生效）。
- 遗留观察：QQ 3.2.30 + NapCat 4.18.18 + bypass + watchdog v6 组合能否长期稳定。

## 现象 Summary（2026-08-14 下午，已被推翻）

~~生产服务器上的 QQ Linux 客户端**周期性崩溃**（掉线），崩溃间隔**不断缩短**：30 分钟 → 20 分钟 → 10 分钟。~~（实为 watchdog 误杀，见上方结论）

- 环境：AlmaLinux 9.2 VPS（香港，64.90.13.42，2C2G + 2GB swap），无头运行（`xvfb-run` + `screen`）
- 组合：**QQ NT 3.2.30-50969**（Linux AppImage 解包注入）+ **NapCat 4.18.18**（latest，2026-08-07）
- 启动方式：`xvfb-run -a qq --no-sandbox -q <uin>`（快速登录）

## 崩溃时间线 Crash timeline（watchdog 日志实录）

```
2026-08-14 12:05:01 8081 down, restarting napcat   ← 间隔 30 分钟
2026-08-14 12:35:01 8081 down, restarting napcat
2026-08-14 13:05:01 8081 down, restarting napcat
2026-08-14 13:35:01 8081 down, restarting napcat
2026-08-14 14:05:01 8081 down, restarting napcat
2026-08-14 14:35:01 8081 down, restarting napcat   ← 之后间隔变 20 分钟
2026-08-14 14:55:01 8081 down, restarting napcat
2026-08-14 15:15:01 8081 down, restarting napcat
2026-08-14 15:35:01 8081 down, restarting napcat   ← 之后约 10 分钟
```

> ⚠️ **以上记录已被重新解读**：这些"down"绝大多数是 watchdog 的 ss 误判（PATH 问题），间隔 30→20→10 分钟 = watchdog 冷却时间调整（v2 30 分钟 → v4 20 分钟 → v5 10 分钟），并非 QQ 真实崩溃周期。仅少数（如 18:36-18:42 需扫码恢复）是真实掉线（风控踢号）。

每次"崩溃"后 watchdog 用 `-q` 快速登录拉起，**15 秒内恢复且免扫码**（token 有效），说明是"小掉线"（客户端崩溃/被踢但凭证未失效），不是凭证失效。

## 证据 Evidence

1. QQ 崩溃日志（`/tmp/qq_start.log`）：
   ```
   fatalSetup
   [BuglyManager.cpp][InitBuglyManager][212]InitBuglyManager path: /root/.config/QQ/crash_files/
   [NativeCrashHandler.cpp][getCrashDetailBeanFromRecord][52]!!!! in NativeCrashHandler getCrashDetailBeanFromRecord, open file error!!!,dumpFilePath:/root/.config/QQ/crash_files/rqd_record.eup.
   ```
   → QQ 原生崩溃处理（Bugly/NativeCrashHandler）被触发，是**客户端进程级崩溃**，不是网络波动。
2. 崩溃后 8081 端口掉监听（`ss -tln | grep 8081` 为空），QQ 进程退出，NapCat 随之退出。

## 已尝试的方案 Attempts（均未根治）

| 方案 | 结果 | 原因 |
|------|------|------|
| watchdog 自动拉起（每分钟检测 + 15 秒快速登录） | ⚠️ 兜底有效但无法阻止崩溃 | 治标 |
| 每日 04:30 主动重启 QQ + 增加 2GB swap | ❌ 无效 | 崩溃周期短于 1 天 |
| **降级 NapCat 4.15.0**（社区口碑稳定版） | ❌ 登录被拒 | 腾讯提示"请下载最新版QQ"——4.15.0 协议特征映射过旧（2026-02），登录服务拒绝 |
| 换 QQ 旧版 3.2.23-44343 / 3.2.27-47256 | ❌ 无法获取 | 腾讯已下架全部旧版安装包（dldir1/dldir1v6/qqdl.gtimg 全线 404） |
| o3HookMode=0（社区假死修复） | 未试 | 待下次验证 |
| **NapCat 反检测 bypass 六项**（hook/window/module/process/container/js） | ⏳ 已开启观察中（2026-08-14 19:07 生效） | 需改**账号级配置** `napcat_<QQ号>.json`（主配置会被覆盖）；开启后 `-q` 快速登录成功、token 不再被清 |
| **升级 QQ 3.2.32-52194**（腾讯 2026-08-10 发布的最新 Linux 版） | ❌ 不兼容已回滚 | NapCat 4.18.18 报"PacketBackend 不支持当前QQ版本架构：3.2.32-52194-x64"（NapCat 未适配 8-10 新版）；等待 NapCat 新版本适配后重试，回滚备份仍在 QQ_332_incompatible |

## 2026-08-14 晚进展 Update（19:15）

1. **腾讯风控实锤**：18:41 用户收到 QQ 安全中心通知"已登录设备风险提醒"——设备 ser678257072092（本服务器）被判"**设备存外挂或其他软件影响QQ正常使用**"，平台已对风险设备下线处理（最后登录 15:45:15）。→ 此前的"崩溃间隔缩短"实际是**客户端崩溃 + 风控踢号叠加**；`-q` 快速登录 token 频繁失效（风控清 token）也得到解释。
2. **反检测开启**：NapCat 自带 bypass 六项反检测（默认全关），已开启并验证生效（启动日志确认加载 true 版）。开启后 19:07 起 `-q` 免扫码登录成功，观察掉线频率是否下降。
3. 若观察期仍频繁被踢，下一步候选：清理 `~/.config/QQ` 风控数据（GitHub Discussion #1888，效果因人而异）、SnowLuma 框架、OpenShamrock 云手机。

## 假设原因 Hypotheses

1. **腾讯对旧协议端的风控施压**：崩溃间隔逐渐缩短（30→20→10 分钟）符合"逐步踢下线"模式；扫码登录时曾出现"请下载最新版QQ"提示，说明腾讯登录服务在推行最新客户端版本。
2. **QQ 3.2.30 客户端自身 bug**：Bugly 原生崩溃日志实锤客户端进程崩溃；社区（LINUX DO 等）大量报告同版本掉线。
3. **账号/设备风控（已实锤 ✅）**：2026-08-14 18:41 收到腾讯官方风险设备通知，服务器设备被判"外挂影响QQ正常使用"并主动下线——NapCat 注入特征被腾讯检测。反检测 bypass 已开启应对（见上方更新）。

## 求助 Help wanted 🙏

如果你遇到过同样问题并解决了，或者知道根因，请在 Issue 里回复，欢迎 PR：
1. 有没有已知的 QQ 3.2.30-50969 崩溃 bug 及官方修复版本号？
2. 腾讯最新 Linux QQ 的下载源（官方已下架旧版，新版在哪里拿）？
3. SnowLuma 或其他框架是否根治过同类问题？
