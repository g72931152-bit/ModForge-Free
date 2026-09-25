@echo off
cd /d "%~dp0backend"
python -m venv .venv
call .venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
