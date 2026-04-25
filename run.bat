@echo off
cd /d "%~dp0"
py -m streamlit run src/app.py
pause
