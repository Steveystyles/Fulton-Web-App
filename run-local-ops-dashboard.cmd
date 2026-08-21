@echo off
setlocal

cd /d "%~dp0"

set "PORT=%FULTONS_LOCAL_OPS_PORT%"
if not defined PORT set "PORT=8765"

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
  "$workingDir=[System.IO.Path]::GetFullPath('%~dp0');" ^
  "$port=[int]'%PORT%';" ^
  "$tokenPath=Join-Path $workingDir 'data\local-ops-access-token';" ^
  "if (!(Test-Path -LiteralPath $tokenPath)) {" ^
  "  $parent=Split-Path -Parent $tokenPath; if (!(Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent | Out-Null };" ^
  "  $bytes=New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Fill($bytes);" ^
  "  $token=[Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_');" ^
  "  [IO.File]::WriteAllText($tokenPath,$token,[Text.UTF8Encoding]::new($false));" ^
  "  & icacls.exe $tokenPath /inheritance:r /grant:r ('{0}:(R,W)' -f [Environment]::UserName) | Out-Null;" ^
  "};" ^
  "$token=[IO.File]::ReadAllText($tokenPath).Trim(); if ($token.Length -lt 32) { throw 'Local Ops token is invalid.' };" ^
  "$healthUrl='http://127.0.0.1:'+$port+'/api/local/ops-config';" ^
  "$headers=@{'X-Fultons-Ops-Token'=$token};" ^
  "$needsStart=$true;" ^
  "try { $response=Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -Headers $headers -TimeoutSec 2; if ($response.StatusCode -eq 200) { $needsStart=$false } } catch {};" ^
  "if ($needsStart) {" ^
  "  $logDir=Join-Path $workingDir 'logs'; if (!(Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null };" ^
  "  $logFile=Join-Path $logDir 'local-ops-dashboard.log';" ^
  "  $launcher='& { Set-Location -LiteralPath '''+$workingDir+'''; $env:FULTONS_LOCAL_OPS_PORT='''+$port+'''; $env:FULTONS_LOCAL_OPS_TOKEN_FILE='''+$tokenPath+'''; $env:FULTONS_MONITOR_ENABLED=''1''; python local_ops_server.py *>> '''+$logFile+''' }';" ^
  "  Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-Command',$launcher -WorkingDirectory $workingDir -WindowStyle Hidden | Out-Null;" ^
  "};" ^
  "for ($attempt=0; $attempt -lt 30; $attempt++) { try { $response=Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -Headers $headers -TimeoutSec 2; if ($response.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Seconds 1 }; exit 1"

if errorlevel 1 (
  echo [ops] Local dashboard did not become ready on 127.0.0.1:%PORT%
  exit /b 1
)

if "%NO_BROWSER%"=="0" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "$tokenPath=Join-Path ([System.IO.Path]::GetFullPath('%~dp0')) 'data\local-ops-access-token';" ^
    "$token=[IO.File]::ReadAllText($tokenPath).Trim();" ^
    "$url='http://127.0.0.1:%PORT%/ops#opsToken='+[Uri]::EscapeDataString($token);" ^
    "$edge=Get-Command msedge.exe -ErrorAction SilentlyContinue;" ^
    "$chrome=Get-Command chrome.exe -ErrorAction SilentlyContinue;" ^
    "if ($edge) { Start-Process -FilePath $edge.Source -ArgumentList ('--app='+$url) | Out-Null; exit 0 };" ^
    "if ($chrome) { Start-Process -FilePath $chrome.Source -ArgumentList ('--app='+$url) | Out-Null; exit 0 };" ^
    "Start-Process $url | Out-Null"
)

exit /b 0
