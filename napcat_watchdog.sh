#!/bin/bash
# NapCat watchdog v6: 8081 掉监听时自动拉起（-q <QQ号> 快速登录，token 有效时免扫码）
# v6 关键修复：ss 在 /usr/sbin，用户 crontab 默认 PATH 不含 → 之前一直"ss not found"误判 8081 down
#             （今天下午"周期崩溃"实为 watchdog 冷却结束就误杀 QQ）。改用绝对路径 /usr/sbin/ss。
# v5 功能保留：拉起前保存崩溃前的 QQ 日志（诊断死因）
MARK=/tmp/napcat_watchdog_mark
if ! /usr/sbin/ss -tln 2>/dev/null | grep -q ':8081 '; then
  if [ -f "$MARK" ] && [ $(( $(date +%s) - $(stat -c %Y "$MARK") )) -lt 600 ]; then
    echo "$(date '+%F %T') 8081 down but in cooldown, skip" >> /var/log/napcat_watchdog.log
    exit 0
  fi
  touch "$MARK"
  echo "$(date '+%F %T') 8081 down, restarting napcat" >> /var/log/napcat_watchdog.log
  # 保存崩溃前日志（保留最近 5 份，防堆积）
  cp /tmp/qq_start.log /tmp/qq_crash_$(date +%Y%m%d_%H%M%S).log 2>/dev/null
  ls -t /tmp/qq_crash_*.log 2>/dev/null | tail -n +6 | xargs -r rm -f
  pkill -x qq 2>/dev/null
  screen -S napcat -X quit 2>/dev/null
  systemctl stop napcat.service 2>/dev/null
  sleep 3
  /usr/bin/screen -dmS napcat bash -c "xvfb-run -a /root/Napcat/opt/QQ/qq --no-sandbox -q 2337295608 > /tmp/qq_start.log 2>&1"
fi
