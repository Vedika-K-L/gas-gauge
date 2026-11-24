@echo off
cd /d "%~dp0"
git add -A
git commit -m "update"
git pull --rebase origin main
git push origin main
echo.
echo Done. Now reboot the app in Streamlit.
pause
