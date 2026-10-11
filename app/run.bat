@echo off
cd /d "%~dp0"
pip install -r requirements.txt -q
start "" http://127.0.0.1:5000/
python app.py
