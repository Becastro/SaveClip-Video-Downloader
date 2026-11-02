@echo off
setlocal
set "ROOT=%~dp0"
set "BUILD_ENV=%ROOT%backend\.build-venv"
set "PYTHON=python"
set "NO_LAUNCH="

if /I "%~1"=="/no-launch" set "NO_LAUNCH=1"

tasklist /FI "IMAGENAME eq SaveClip.exe" /NH | find /I "SaveClip.exe" >nul
if errorlevel 1 (
  goto :app_closed
)
echo Feche o SaveClip antes de compilar ou gerar o instalador.
exit /b 1

:app_closed

where py >nul 2>nul
if not errorlevel 1 set "PYTHON=py -3"

echo [1/4] Preparando o ambiente Python...
if not exist "%BUILD_ENV%\Scripts\python.exe" (
  %PYTHON% -m venv "%BUILD_ENV%"
  if errorlevel 1 goto :failed
)

echo [2/4] Instalando dependencias do app e do empacotador...
"%BUILD_ENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%ROOT%requirements-build.txt"
if errorlevel 1 goto :failed

echo [3/4] Compilando a interface web...
pushd "%ROOT%frontend"
call npm ci
if errorlevel 1 (
  popd
  goto :failed
)
call npm run build
if errorlevel 1 (
  popd
  goto :failed
)
popd

echo [4/4] Criando dist\SaveClip.exe...
"%BUILD_ENV%\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed --name SaveClip --icon "%ROOT%assets\saveclip.ico" --distpath "%ROOT%dist" --workpath "%ROOT%build\SaveClip" --specpath "%ROOT%build" --paths "%ROOT%backend" --hidden-import app.main --copy-metadata yt-dlp --add-data "%ROOT%frontend\dist;frontend_dist" --collect-all imageio_ffmpeg --collect-all webview "%ROOT%backend\launcher.py"
if errorlevel 1 goto :failed

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%Prepare-SaveClip-Distribution.ps1"
if errorlevel 1 goto :failed

echo.
echo Build concluido.
if defined NO_LAUNCH exit /b 0

echo Abrindo SaveClip...
start "SaveClip" /D "%ROOT%dist" "%ROOT%dist\SaveClip.exe"
exit /b 0

:failed
echo.
echo A build falhou. Leia a mensagem acima, corrija o problema e execute este arquivo novamente.
pause
exit /b 1
