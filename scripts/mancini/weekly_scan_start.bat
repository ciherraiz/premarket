@echo off
REM Ejecuta el scan semanal Big Picture View de Mancini.
REM Diseñado para Windows Task Scheduler: cada 2h, Sab-Dom, 18:00-00:00 CEST.
REM El script es idempotente: sobreescribe el plan semanal si ya existe.

cd /d "C:\Users\ciher\Documents\Development\premarket"

set PATH=C:\Users\ciher\.cargo\bin;%PATH%

echo [%date% %time%] Arrancando weekly scan Mancini... >> logs\mancini_scheduler.log

uv run python scripts/mancini/run_mancini.py weekly-scan >> logs\mancini_scheduler.log 2>&1

echo [%date% %time%] Weekly scan finalizado (exit code: %ERRORLEVEL%) >> logs\mancini_scheduler.log
