@echo off
cd /d "%~dp0.."
taskkill /f /im MemWise.exe >nul 2>&1
pyinstaller MemWise.spec --distpath dist --workpath build --noconfirm
echo 打包完成！exe 位于 dist 目录
pause
