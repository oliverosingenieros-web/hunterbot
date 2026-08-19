@echo off
title HunterBot - Bot Interactivo de Telegram
echo ========================================================
echo   Iniciando HunterBot con Inteligencia Artificial (Gemini)
echo ========================================================
echo.

cd /d "C:\Users\olive\.gemini\antigravity\scratch\hunterbot"
set PYTHONPATH=src

echo Verificando dependencias...
py -m pip install -e . >nul 2>&1 || python -m pip install -e . >nul 2>&1

echo.
echo ========================================================
echo   Bot activo. Escuchando mensajes de Telegram...
echo   (No cierres esta ventana para mantener el bot activo)
echo ========================================================
echo.

python -m hunterbot.telegram_bot || py -m hunterbot.telegram_bot

pause

