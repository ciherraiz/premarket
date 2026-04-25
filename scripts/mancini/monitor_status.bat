@echo off
REM Muestra el estado de salud del sistema Mancini en pantalla.

title Mancini status

cd /d "C:\Users\ciher\Documents\Development\premarket"

set PYTHONUTF8=1

uv run python scripts/mancini/run_mancini.py health

echo.
pause
