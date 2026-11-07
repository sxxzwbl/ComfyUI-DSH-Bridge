@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title ComfyUI-DSH-Bridge 卸载器

set "HERE=%~dp0"
set "PLUGIN=%HERE:~0,-1%"
for %%I in ("%PLUGIN%\..") do set "CN=%%~fI"
for %%I in ("%CN%\..") do set "COMFY=%%~fI"
for %%I in ("%COMFY%\..") do set "ROOT=%%~fI"

echo ============================================================
echo   ComfyUI-DSH-Bridge 卸载器
echo ============================================================
echo   插件目录 : %PLUGIN%
echo   ComfyUI  : %COMFY%
echo.
echo   会清掉安装器写进 DSH home 的东西：harness profile、两处插件副本、
echo   14 个 skill、桥接配置。凭据和会话记录不动。
echo.

netstat -ano | findstr /R /C:":8188 .*LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo   [提醒] 8188 端口正在被占用，ComfyUI 可能还开着。
  echo          卸载会改写 config.json，建议先关掉 ComfyUI 再继续。
  echo.
)

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
  echo        从自带 python 目录的 ComfyUI 整合包里运行本文件，或安装 Python 3.10 以上。
  echo.
  pause
  exit /b 1
)

echo   Python   : %PY% %PYARG%
echo.

if /I "%~1"=="--yes" goto do_uninstall

echo 第一步：预演（只列清单，不删任何东西）
echo.
"%PY%" %PYARG% "%PLUGIN%\scripts\uninstall.py" %*
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" goto failed

choice /C YN /M "确认删除上面这些吗（harness profile 会改名备份，不是直接删）"
if errorlevel 2 goto cancelled
echo.

:do_uninstall
"%PY%" %PYARG% "%PLUGIN%\scripts\uninstall.py" --yes %*
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" goto failed
echo ============================================================
echo   清理完成。下一步：
echo     1. 把新版放进 custom_nodes 覆盖同名目录
echo     2. 运行 install.bat
echo ============================================================
echo.
pause
exit /b 0

:cancelled
echo 已取消，什么都没删。
echo.
pause
exit /b 1

:failed
echo ============================================================
echo   卸载器退出码 %RC%，请查看上面的提示。
echo ============================================================
echo.
pause
exit /b %RC%
