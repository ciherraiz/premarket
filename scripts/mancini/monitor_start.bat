@echo off
REM Lanza el monitor Mancini /ES como proceso de larga duración.
REM Diseñado para ejecutarse desde Windows Task Scheduler a las 13:00 CEST (07:00 ET).
REM El monitor corre hasta 16:00 ET y se auto-finaliza.

title Mancini Monitor /ES

cd /d "C:\Users\ciher\Documents\Development\premarket"

set PATH=C:\Users\ciher\.cargo\bin;%PATH%

echo [%date% %time%] Arrancando monitor Mancini... >> logs\mancini_monitor.log

uv run python scripts/mancini/run_mancini.py monitor

echo [%date% %time%] Monitor finalizado >> logs\mancini_monitor.log
