@echo off
REM Lanza el monitor Mancini /ES como proceso de larga duración.
REM Diseñado para ejecutarse desde Windows Task Scheduler a las 14:00 CEST (08:00 ET).
REM El monitor corre hasta 11:00 ET y se auto-finaliza.

cd /d "C:\Users\ciher\Documents\Development\premarket"

set PATH=C:\Users\ciher\.cargo\bin;%PATH%

echo [%date% %time%] Arrancando monitor Mancini... >> logs\mancini_scheduler.log

uv run python scripts/mancini/run_mancini.py monitor >> logs\mancini_scheduler.log 2>&1

echo [%date% %time%] Monitor finalizado >> logs\mancini_scheduler.log
