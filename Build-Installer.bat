@echo off
setlocal
set "ROOT=%~dp0"
set "ISCC="

where ISCC.exe >nul 2>nul
if not errorlevel 1 set "ISCC=ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if not defined ISCC (
  echo Instale o Inno Setup 6 para criar o instalador.
  echo O aplicativo pronto nao precisa do Inno Setup para abrir.
  pause
  exit /b 1
)

echo Atualizando o aplicativo antes de criar o instalador...
call "%ROOT%Build-SaveClip.bat" /no-launch
if errorlevel 1 (
  echo Nao foi possivel atualizar o aplicativo. O instalador nao foi gerado.
  pause
  exit /b 1
)

if not exist "%ROOT%dist\SaveClip.exe" (
  echo SaveClip.exe nao foi encontrado. Execute Build-SaveClip.bat primeiro.
  pause
  exit /b 1
)

"%ISCC%" "%ROOT%SaveClip-Setup.iss"
if errorlevel 1 (
  echo A criacao do instalador falhou.
  pause
  exit /b 1
)

echo Instalador criado em dist\installer\SaveClip-Setup.exe
exit /b 0
