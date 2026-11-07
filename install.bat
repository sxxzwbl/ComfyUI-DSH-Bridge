@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title ComfyUI-DSH-Bridge 安装器

set "HERE=%~dp0"
set "PLUGIN=%HERE:~0,-1%"
for %%I in ("%PLUGIN%\..") do set "CN=%%~fI"
for %%I in ("%CN%\..") do set "COMFY=%%~fI"
for %%I in ("%COMFY%\..") do set "ROOT=%%~fI"

echo ============================================================
echo   ComfyUI-DSH-Bridge 安装器
echo ============================================================
echo   插件目录 : %PLUGIN%
echo   ComfyUI  : %COMFY%
echo.
echo 用法：直接双击            = 自动安装
echo       --dry-run           = 只看不改
echo       --api-key sk-xxx    = 用 API key 认证（DSH 没登录过时用这个）
echo       拖 harness 文件夹过来 = 手动指定 DSH 安装目录
echo.

netstat -ano | findstr /R /C:":8188 .*LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo   [提醒] 8188 端口正在被占用，ComfyUI 可能还开着。
  echo          安装会写入 config.json 和 harness profile，建议先关掉 ComfyUI。
  echo.
  choice /C YN /M "仍要继续吗"
  if errorlevel 2 exit /b 1
)
echo.

set "PY="
set "PYARG="
for %%P in (
  "%COMFY%\python_embeded\python.exe"
  "%COMFY%\python\python.exe"
  "%ROOT%\python_embeded\python.exe"
  "%ROOT%\python\python.exe"
  "%ROOT%\..\python\python.exe"
  "%ROOT%\..\python_embeded\python.exe"
) do (
  if not defined PY if exist "%%~P" set "PY=%%~P"
)
if not defined PY (
  for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PY set "PY=%%P"
  )
)
if not defined PY (
  for /f "delims=" %%P in ('where py 2^>nul') do (
    if not defined PY (
      set "PY=%%P"
      set "PYARG=-3"
    )
  )
)

if not defined PY (
  echo [错误] 没找到 Python。
  echo        请安装 Python 3.10 以上（安装时勾选 Add to PATH），
  echo        或者从自带 python 目录的 ComfyUI 整合包里运行本文件。
  echo.
  pause
  exit /b 1
)

echo   Python   : %PY% %PYARG%
echo.

rem 第一个参数如果是文件夹，就当作 --harness，支持把 harness 目录拖到本文件上
set "EXTRAS=%*"
if not "%~1"=="" if exist "%~1\" set "EXTRAS=--harness "%~1""

echo 正在运行 scripts\install.py ...（想先预览就带参数 --dry-run）
echo.

"%PY%" %PYARG% "%PLUGIN%\scripts\install.py" %EXTRAS%
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo ============================================================
  echo   安装完成。启动 ComfyUI，日志里应出现：
  echo   [DSH-Bridge] loaded; ... nodes=DSH_ContactSheet,DSH_PromptNode
  echo ============================================================
) else (
  echo ============================================================
  echo   安装器退出码 %RC%，请查看上面的提示。
  echo ============================================================
)
echo.
pause
exit /b %RC%