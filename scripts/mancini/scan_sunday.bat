@echo off
REM Ejecuta el scan de tweets de Mancini los domingos por la tarde.
REM Diseñado para Windows Task Scheduler: cada 10 min, Dom, 18:00-23:00 CEST.
REM El script es idempotente: si no hay tweets nuevos, termina sin error.

title Mancini Scan (Domingo)

cd /d "C:\Users\ciher\Documents\Development\premarket"

set PATH=C:\Users\ciher\.cargo\bin;%PATH%

echo [%date% %time%] Arrancando scan Mancini domingo... >> logs\mancini_scan.log

uv run python scripts/mancini/run_mancini.py scan

echo [%date% %time%] Scan domingo finalizado (exit code: %ERRORLEVEL%) >> logs\mancini_scan.log
