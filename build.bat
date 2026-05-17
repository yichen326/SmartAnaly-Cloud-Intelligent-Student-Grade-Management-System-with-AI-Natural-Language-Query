@echo off
chcp 65001 >nul
title 智析云途 - 打包工具
echo ====================================
echo   智析云途 - 一键打包工具
echo ====================================
echo.
echo [1/3] 检查环境...
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

echo [2/3] 安装/更新依赖...
python -m pip install --upgrade pip -q
pip install pyinstaller requests openpyxl -q
if %ERRORLEVEL% neq 0 (
    echo [警告] 部分依赖安装失败，请手动执行: pip install pyinstaller requests openpyxl
)

echo [3/3] 开始打包...
echo.
echo 打包参数:
echo   - 单文件模式
echo   - 窗口应用 (无控制台)
echo   - 包含数据文件和配置文件
echo.

pyinstaller --onefile --windowed --name "智析云途" ^
    --add-data "config.json;." ^
    --add-data "students_data.txt;." ^
    --add-data "school_final.db;." ^
    --hidden-import "requests" ^
    --hidden-import "openpyxl" ^
    --hidden-import "sqlite3" ^
    --hidden-import "PyQt5" ^
    --hidden-import "PyQt5.QtWidgets" ^
    --hidden-import "PyQt5.QtCore" ^
    --hidden-import "PyQt5.QtGui" ^
    --clean --noconfirm main.py

if %ERRORLEVEL% equ 0 (
    echo.
    echo ====================================
    echo  打包成功！
    echo ====================================
    echo.
    echo 输出文件: dist\智析云途.exe
    echo.
    echo 首次使用前，请确保:
    echo   1. dist\config.json 已填写 API Key
    echo   2. dist\students_data.txt 存在（可选）
    echo   3. school_final.db 会被自动创建
    echo.
    echo 按任意键打开输出目录...
    pause >nul
    explorer dist\
) else (
    echo.
    echo [错误] 打包失败，请检查上方错误信息
    echo 尝试手动执行: pyinstaller build.spec
)
pause
