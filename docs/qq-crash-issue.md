# QQ 客户端周期性崩溃问题追踪（Crash Investigation）

> 状态：**未解决，寻求高手帮助** · Status: unresolved, help wanted
> 相关 Issue：#见 GitHub Issues

## 现象 Summary

生产服务器上的 QQ Linux 客户端**周期性崩溃**（掉线），崩溃间隔**不断缩短**：30 分钟 → 20 分钟 → 10 分钟。

- 环境：Ubuntu/Debian VPS（美西，64.90.13.42），无头运行（`xvfb-run` + `screen`）
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

## 假设原因 Hypotheses

1. **腾讯对旧协议端的风控施压**：崩溃间隔逐渐缩短（30→20→10 分钟）符合"逐步踢下线"模式；扫码登录时曾出现"请下载最新版QQ"提示，说明腾讯登录服务在推行最新客户端版本。
2. **QQ 3.2.30 客户端自身 bug**：Bugly 原生崩溃日志实锤客户端进程崩溃；社区（LINUX DO 等）大量报告同版本掉线。
3. **账号风控**：该 QQ 号为较新账号，社区经验"新号头几天频繁掉线，挂 1-2 周稳定"。

## 求助 Help wanted 🙏

如果你遇到过同样问题并解决了，或者知道根因，请在 Issue 里回复，欢迎 PR：
1. 有没有已知的 QQ 3.2.30-50969 崩溃 bug 及官方修复版本号？
2. 腾讯最新 Linux QQ 的下载源（官方已下架旧版，新版在哪里拿）？
3. SnowLuma 或其他框架是否根治过同类问题？
