@echo off
setlocal

cd /d "%~dp0"

set "PORT=%FULTONS_LOCAL_OPS_PORT%"
if not defined PORT set "PORT=8765"

set "APP_URL=http://127.0.0.1:%PORT%/ops"
set "HEALTH_URL=http://127.0.0.1:%PORT%/api/local/ops-monitor"
set "NO_BROWSER=0"

if /I "%~1"=="--no-browser" set "NO_BROWSER=1"
if /I "%~1"=="/background" set "NO_BROWSER=1"

if not exist "dist\index.html" (
  echo [ops] Frontend build missing. Running npm build...
  call npm.cmd run build
  if errorlevel 1 exit /b %errorlevel%
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$healthUrl='%HEALTH_URL%';" ^
  "$workingDir=[System.IO.Path]::GetFullPath('%~dp0');" ^
  "$needsStart=$true;" ^
  "try { $response=Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 2; if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { $needsStart=$false } } catch {};" ^
  "if ($needsStart) {" ^
  "  $logDir = Join-Path $workingDir 'logs';" ^
  "  if (!(Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null };" ^
  "  $logFile = Join-Path $logDir 'local-ops-dashboard.log';" ^
  "  $keyPath = Join-Path $env:USERPROFILE '.ssh\codex_fultons_ed25519';" ^
  "  $launcher = '& { Set-Location -LiteralPath ''' + $workingDir + '''; $env:FULTONS_HOST=''127.0.0.1''; $env:FULTONS_PORT=''%PORT%''; $env:FULTONS_COOKIE_SECURE=''0''; $env:FULTONS_ALLOWED_ORIGINS=''http://127.0.0.1:%PORT%,http://localhost:%PORT%''; $env:FULTONS_MONITOR_ENABLED=''1''; $env:FULTONS_LOCAL_OPS_ENABLED=''1''; if (-not $env:FULTONS_MONITOR_SSH_TARGET) { $env:FULTONS_MONITOR_SSH_TARGET=''ste@192.168.0.15'' }; if (-not $env:FULTONS_MONITOR_SSH_KEY_PATH) { $env:FULTONS_MONITOR_SSH_KEY_PATH=''' + $keyPath + ''' }; if (-not $env:FULTONS_MONITOR_PUBLIC_HEALTH_URL) { $env:FULTONS_MONITOR_PUBLIC_HEALTH_URL=''https://fultons-quiz.co.uk/api/health'' }; python production_server.py *>> ''' + $logFile + ''' }';" ^
  "  Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-Command',$launcher -WorkingDirectory $workingDir -WindowStyle Hidden | Out-Null;" ^
  "}" ^
  "for ($attempt = 0; $attempt -lt 30; $attempt++) { try { $response=Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 2; if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { exit 0 } } catch {}; Start-Sleep -Seconds 1 }; exit 1"

if errorlevel 1 (
  echo [ops] Local dashboard did not become ready at %HEALTH_URL%
  exit /b 1
)

if "%NO_BROWSER%"=="0" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "$url='%APP_URL%';" ^
    "$edge = Get-Command msedge.exe -ErrorAction SilentlyContinue;" ^
    "$chrome = Get-Command chrome.exe -ErrorAction SilentlyContinue;" ^
    "if ($edge) { Start-Process -FilePath $edge.Source -ArgumentList '--app=' + $url | Out-Null; exit 0 }" ^
    "if ($chrome) { Start-Process -FilePath $chrome.Source -ArgumentList '--app=' + $url | Out-Null; exit 0 }" ^
    "Start-Process $url | Out-Null"
)

exit /b 0
