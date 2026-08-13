@echo off
chcp 65001 >nul
rem ============================================
rem  启动 JM娘 主程序（连接 NapCat）
rem  本机走代理(7890)；海外服务器部署时去掉下面这行即可直连
rem ============================================
cd /d "%~dp0"
set JM_PROXY=http://127.0.0.1:7890
echo 启动 JM娘 ...
start "JM娘" python -X utf8 jm_niang.py
echo 已启动。日志输出在 JM娘 窗口。
