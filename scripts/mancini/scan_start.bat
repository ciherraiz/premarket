@echo off
REM Ejecuta el scan de tweets de Mancini y extrae el plan diario.
REM Diseñado para Windows Task Scheduler: cada 10 min, L-V, 13:00-22:00 CEST.
REM El script es idempotente: si no hay tweets nuevos, termina sin error.

cd /d "C:\Users\ciher\Documents\Development\premarket"

set PATH=C:\Users\ciher\.cargo\bin;%PATH%

echo [%date% %time%] Arrancando scan Mancini... >> logs\mancini_scheduler.log

uv run python scripts/mancini/run_mancini.py scan >> logs\mancini_scheduler.log 2>&1

echo [%date% %time%] Scan finalizado (exit code: %ERRORLEVEL%) >> logs\mancini_scheduler.log
