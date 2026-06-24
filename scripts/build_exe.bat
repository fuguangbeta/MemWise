@echo off
cd /d "%~dp0.."
echo 正在安装 PyInstaller...
pip install pyinstaller -q
echo 正在打包为单文件 exe...
if exist MemWise.exe del MemWise.exe
pyinstaller --onefile --noconsole --name MemWise --add-data "core;core" --distpath . memwise_gui.py
echo 打包完成！exe 位于当前目录
pause
