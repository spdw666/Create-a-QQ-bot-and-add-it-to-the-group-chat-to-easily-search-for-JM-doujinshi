#!/bin/bash
# NapCat watchdog v5: 8081 掉监听时自动拉起（-q <QQ号> 快速登录，token 有效时免扫码）
# v5 新增：拉起前保存崩溃前的 QQ 日志（诊断死因：fatalSetup=客户端崩 / 账号状态变更为离线=被踢）
MARK=/tmp/napcat_watchdog_mark
if ! ss -tln 2>/dev/null | grep -q ':8081 '; then
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
