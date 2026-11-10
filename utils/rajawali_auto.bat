@echo off
REM Report pagi otomatis lewat Prisma + Rajawali. Tambah --kirim untuk mengirim ke grup.
REM Minta hak Administrator (dibutuhkan untuk memblok mouse/keyboard selama otomasi berjalan).
cd /d "%~dp0.."
net session >nul 2>&1
if %errorlevel% neq 0 (
    if "%~1"=="" (
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    ) else (
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
    )
    exit /b
)
python utils\rajawali_auto.py %*
pause
