@echo off
REM Lanza el monitor Mancini /ES para la sesión dominical.
REM Diseñado para Windows Task Scheduler a las 00:00 CEST lunes (18:00 ET domingo).
REM Futuros abren domingo 18:00 ET. Monitor corre hasta 00:00 ET.
REM El lunes a las 13:00 CEST arranca el monitor normal.

title Mancini Monitor /ES (Domingo)

cd /d "C:\Users\ciher\Documents\Development\premarket"

set PATH=C:\Users\ciher\.cargo\bin;%PATH%

echo [%date% %time%] Arrancando monitor Mancini domingo... >> logs\mancini_monitor.log

uv run python scripts/mancini/run_mancini.py monitor --start 18 --end 24

echo [%date% %time%] Monitor domingo finalizado >> logs\mancini_monitor.log
