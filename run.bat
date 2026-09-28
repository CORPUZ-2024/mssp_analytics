@echo off
cd /d "%~dp0"
rem Prefer the repo venv (Python 3.11 + Streamlit 1.32); fall back to the py launcher.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m streamlit run streamlit_dashboard/app.py
) else (
    py -m streamlit run streamlit_dashboard/app.py
)
pause
