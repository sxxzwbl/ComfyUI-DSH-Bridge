@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title ComfyUI-DSH-Bridge 诊断

set "HERE=%~dp0"
set "PLUGIN=%HERE:~0,-1%"
for %%I in ("%PLUGIN%\..") do set "CN=%%~fI"
for %%I in ("%CN%\..") do set "COMFY=%%~fI"
for %%I in ("%COMFY%\..") do set "ROOT=%%~fI"

echo ============================================================
echo   ComfyUI-DSH-Bridge 诊断
echo ============================================================
echo   插件目录 : %PLUGIN%
echo   ComfyUI  : %COMFY%
echo.
echo   会依次检查：代码版本、config、认证、ComfyUI 的代理、网络可达性、
echo   harness 进程与管道，然后实测发一条消息。最后一行是结论。
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
  echo [错误] 没找到 Python。从自带 python 的 ComfyUI 整合包里运行本文件。
  echo.
  pause
  exit /b 1
)

echo   Python   : %PY% %PYARG%
echo.
echo ------------------------------------------------------------
echo.

"%PY%" %PYARG% "%PLUGIN%\scripts\doctor.py" --ask %*
set "RC=%ERRORLEVEL%"
set "REPORT=%PLUGIN%\logs\doctor.txt"

echo.
echo ------------------------------------------------------------
if "%RC%"=="0" (
  echo 诊断结束。上面最后那一行「结论：」就是答案。
  if exist "%REPORT%" echo 同样的内容也存到了：%REPORT%
  echo.
  echo 要发给别人看，直接发这个文件就行，不用截图。
) else (
  echo 诊断器退出码 %RC%，请看上面的报错。
)
echo.
pause
exit /b %RC%
