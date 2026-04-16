@echo off
REM Ejecuta el scan de tweets de Mancini y extrae el plan diario.
REM Diseñado para Windows Task Scheduler: cada 10 min, L-V, 13:00-22:00 CEST.
REM El script es idempotente: si no hay tweets nuevos, termina sin error.

title Mancini Scan

cd /d "C:\Users\ciher\Documents\Development\premarket"

set PATH=C:\Users\ciher\.cargo\bin;%PATH%

echo [%date% %time%] Arrancando scan Mancini... >> logs\mancini_scan.log

uv run python scripts/mancini/run_mancini.py scan

echo [%date% %time%] Scan finalizado (exit code: %ERRORLEVEL%) >> logs\mancini_scan.log
