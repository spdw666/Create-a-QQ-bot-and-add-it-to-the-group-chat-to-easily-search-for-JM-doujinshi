Option Explicit

' ASCII-only wrapper for Windows Script Host compatibility.
Dim scriptDir, command
scriptDir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\") - 1)
command = "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & scriptDir & "\run_local_watchdog.ps1"""
CreateObject("WScript.Shell").Run command, 0, False
