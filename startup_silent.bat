@echo off
cd /d "C:\Users\Asus\Desktop\SPIDY-AI"
call "c:\Users\Asus\venv\Scripts\activate.bat"
start /min "SPIDY-AI" python main.py >nul 2>&1
