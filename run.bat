@echo off
cd /d "%~dp0"
py -m streamlit run streamlit_dashboard/app.py
pause
