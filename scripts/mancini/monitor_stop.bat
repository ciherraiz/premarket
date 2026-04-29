@echo off
REM Para el sistema Mancini limpiamente.
REM Usa stop-day: señaliza al monitor para que termine de forma ordenada.
REM Pasar el argumento "force" para kill inmediato: monitor_stop.bat force

title Mancini stop-day

cd /d "C:\Users\ciher\Documents\Development\premarket"

set PATH=C:\Users\ciher\.cargo\bin;%PATH%
set PYTHONUTF8=1

echo [%date% %time%] Ejecutando stop-day... >> logs\mancini_startday.log

if "%1"=="force" (
    uv run python scripts/mancini/run_mancini.py stop-day --force >> logs\mancini_startday.log 2>&1
) else (
    uv run python scripts/mancini/run_mancini.py stop-day >> logs\mancini_startday.log 2>&1
)

echo [%date% %time%] stop-day finalizado (exit code: %ERRORLEVEL%) >> logs\mancini_startday.log
