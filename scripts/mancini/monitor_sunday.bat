@echo off
REM Lanza el monitor Mancini /ES para la sesión dominical.
REM Diseñado para Windows Task Scheduler a las 19:00 CEST (13:00 ET).
REM Futuros abren domingo 18:00 ET. Monitor corre hasta 23:59 ET.
REM El lunes a las 13:00 CEST arranca el monitor normal.

cd /d "C:\Users\ciher\Documents\Development\premarket"

set PATH=C:\Users\ciher\.cargo\bin;%PATH%

echo [%date% %time%] Arrancando monitor Mancini domingo... >> logs\mancini_scheduler.log

uv run python scripts/mancini/run_mancini.py monitor --start 13 --end 24 >> logs\mancini_scheduler.log 2>&1

echo [%date% %time%] Monitor domingo finalizado >> logs\mancini_scheduler.log
