@echo off
REM Lanza el sistema Mancini para la jornada.
REM Usa start-day: idempotente, gestiona PID file, mata huérfanos.
REM Diseñado para Windows Task Scheduler a las 09:00 CEST (03:00 ET).

title Mancini start-day

cd /d "C:\Users\ciher\Documents\Development\premarket"

set PATH=C:\Users\ciher\.cargo\bin;%PATH%
set PYTHONUTF8=1

echo [%date% %time%] Ejecutando start-day... >> logs\mancini_startday.log

uv run python scripts/mancini/run_mancini.py start-day >> logs\mancini_startday.log 2>&1

echo [%date% %time%] start-day finalizado (exit code: %ERRORLEVEL%) >> logs\mancini_startday.log
