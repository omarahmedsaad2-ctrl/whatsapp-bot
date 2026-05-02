@echo off
chcp 65001 >nul
title WhatsApp Bot - Auto Restart
color 0A

echo ========================================
echo   🤖 WhatsApp Bot - Auto Restart Mode
echo ========================================
echo.

:loop
echo [%date% %time%] Starting bot...
cd /d "c:\Users\LILMAR\Desktop\whatsapp-bot"
"C:\Users\LILMAR\global_python_env\python.exe" main.py

echo.
echo [%date% %time%] Bot stopped. Restarting in 5 seconds...
timeout /t 5 /nobreak >nul
goto loop
