@echo off
setlocal
set "APP=%~dp0dist\SaveClip.exe"

if not exist "%APP%" (
  echo O aplicativo ainda nao foi compilado.
  echo Execute Build-SaveClip.bat uma vez para criar o executavel.
  pause
  exit /b 1
)

start "SaveClip" /D "%~dp0dist" "%APP%"
exit /b 0
