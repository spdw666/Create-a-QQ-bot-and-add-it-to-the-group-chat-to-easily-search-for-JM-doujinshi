#!/bin/bash
# NapCat watchdog v4: 8081 掉监听时自动拉起（-q <QQ号> 快速登录，token 有效时免扫码）
MARK=/tmp/napcat_watchdog_mark
if ! ss -tln 2>/dev/null | grep -q ':8081 '; then
  if [ -f "$MARK" ] && [ $(( $(date +%s) - $(stat -c %Y "$MARK") )) -lt 600 ]; then
    exit 0
  fi
  touch "$MARK"
  echo "$(date '+%F %T') 8081 down, restarting napcat" >> /var/log/napcat_watchdog.log
  pkill -x qq 2>/dev/null
  screen -S napcat -X quit 2>/dev/null
  systemctl stop napcat.service 2>/dev/null
  sleep 3
  /usr/bin/screen -dmS napcat bash -c "xvfb-run -a /root/Napcat/opt/QQ/qq --no-sandbox -q 2337295608 > /tmp/qq_start.log 2>&1"
fi
