#!/bin/bash
# QQ 每日凌晨定时重启（清累积状态，降低运行中崩溃概率；-q 快速登录免扫码）
echo "$(date '+%F %T') scheduled daily restart" >> /var/log/napcat_watchdog.log
pkill -x qq 2>/dev/null
screen -S napcat -X quit 2>/dev/null
sleep 5
/usr/bin/screen -dmS napcat bash -c "xvfb-run -a /root/Napcat/opt/QQ/qq --no-sandbox -q 2337295608 > /tmp/qq_start.log 2>&1"
