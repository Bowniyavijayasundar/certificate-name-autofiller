# Certificate Name Autofiller - one-click launcher for Windows.
# Started by run-app.bat. Installs what is missing, builds the web app once, starts the server
# and opens the browser. Keep this window open while using the app; close it to stop.
# Options: -Port 8100 (first port to try), -NoBrowser (do not open the browser).
param([switch]$NoBrowser, [int]$Port = 8000)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Venv = Join-Path $Backend ".venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"
try { $Host.UI.RawUI.WindowTitle = "Certificate Name Autofiller" } catch {}

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Stop-WithError([string]$Message) {
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Update-PathFromSystem {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

function Install-WithWinget([string]$Id, [string]$Name, [string]$Url) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Stop-WithError "$Name is not installed. Install it from $Url, then run run-app.bat again."
    }
    $answer = Read-Host "$Name is not installed. Install it now? (Y/N)"
    if ($answer -notmatch '^[Yy]') {
        Stop-WithError "$Name is required. Install it from $Url, then run run-app.bat again."
    }
    winget install --id $Id -e --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Stop-WithError "Installing $Name failed. Install it from $Url, then run run-app.bat again." }
    Update-PathFromSystem
}

function Find-Python {
    $candidates = @(
        @{ Exe = "py"; Args = @("-3") },
        @{ Exe = "python"; Args = @() },
        @{ Exe = "python3"; Args = @() }
    )
    foreach ($c in $candidates) {
        if (-not (Get-Command $c.Exe -ErrorAction SilentlyContinue)) { continue }
        $versionArgs = $c.Args + @("-c", "import sys; print('%d.%d' % sys.version_info[:2])")
        try { $version = & $c.Exe @versionArgs 2>$null | Select-Object -First 1 } catch { continue }
        if ($version -match '^3\.(\d+)$' -and [int]$Matches[1] -ge 10) { return $c }
    }
    return $null
}

function Find-Node {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) { return $false }
    $version = (& node --version) 2>$null
    return ($version -match '^v(\d+)\.' -and [int]$Matches[1] -ge 18)
}

function Get-Sha256([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash }

function Test-OurApp([int]$Port) {
    try { return (Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2).status -eq "ok" } catch { return $false }
}

function Test-PortFree([int]$Port) {
    $listener = $null
    try {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($listener) { $listener.Stop() }
    }
}

Write-Host "Certificate Name Autofiller" -ForegroundColor Green
Write-Host "Project folder: $Root"

# ---------------------------------------------------------------- 1. Python backend
Write-Step "Checking Python (3.10 or newer)"
$python = Find-Python
if (-not $python) {
    Install-WithWinget "Python.Python.3.12" "Python 3.12" "https://www.python.org/downloads/"
    $python = Find-Python
    if (-not $python) { Stop-WithError "Python was installed but is not available yet. Close this window and run run-app.bat again." }
}
Write-Host "Using: $($python.Exe) $($python.Args -join ' ')"

if (-not (Test-Path -LiteralPath $VenvPy)) {
    Write-Step "Creating the Python environment (first run only)"
    $venvArgs = $python.Args + @("-m", "venv", $Venv)
    & $python.Exe @venvArgs
    if ($LASTEXITCODE -ne 0) { Stop-WithError "Could not create the Python environment." }
}

$requirements = Join-Path $Backend "requirements.txt"
$requirementsStamp = Join-Path $Venv ".requirements.sha256"
$requirementsHash = Get-Sha256 $requirements
if (-not (Test-Path -LiteralPath $requirementsStamp) -or (Get-Content -LiteralPath $requirementsStamp) -ne $requirementsHash) {
    Write-Step "Installing backend packages (first run takes a few minutes)"
    & $VenvPy -m pip install --upgrade pip --disable-pip-version-check -q
    & $VenvPy -m pip install -r $requirements --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { Stop-WithError "Installing backend packages failed. Check your internet connection and try again." }
    Set-Content -LiteralPath $requirementsStamp -Value $requirementsHash
} else {
    Write-Host "Backend packages are up to date."
}

# ---------------------------------------------------------------- 2. Web interface (built once)
$distIndex = Join-Path $Frontend "dist\index.html"
$sources = @(Get-ChildItem -LiteralPath (Join-Path $Frontend "src") -Recurse -File) +
           @(Get-Item -LiteralPath (Join-Path $Frontend "index.html"), (Join-Path $Frontend "package.json"),
                       (Join-Path $Frontend "vite.config.ts"), (Join-Path $Frontend "tailwind.config.js"))
$needsBuild = -not (Test-Path -LiteralPath $distIndex)
if (-not $needsBuild) {
    $builtAt = (Get-Item -LiteralPath $distIndex).LastWriteTimeUtc
    $needsBuild = [bool]($sources | Where-Object { $_.LastWriteTimeUtc -gt $builtAt } | Select-Object -First 1)
}

if ($needsBuild) {
    Write-Step "Checking Node.js (needed once to build the web interface)"
    if (-not (Find-Node)) {
        Install-WithWinget "OpenJS.NodeJS.LTS" "Node.js LTS" "https://nodejs.org/"
        if (-not (Find-Node)) { Stop-WithError "Node.js was installed but is not available yet. Close this window and run run-app.bat again." }
    }
    Push-Location $Frontend
    try {
        $lock = Join-Path $Frontend "package-lock.json"
        $nodeModules = Join-Path $Frontend "node_modules"
        $lockStamp = Join-Path $nodeModules ".lock.sha256"
        $lockHash = Get-Sha256 $lock
        if (-not (Test-Path -LiteralPath $lockStamp) -or (Get-Content -LiteralPath $lockStamp) -ne $lockHash) {
            Write-Step "Installing web interface packages"
            & npm.cmd ci --no-fund --no-audit
            if ($LASTEXITCODE -ne 0) { Stop-WithError "Installing web interface packages failed." }
            Set-Content -LiteralPath $lockStamp -Value $lockHash
        }
        Write-Step "Building the web interface"
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { Stop-WithError "Building the web interface failed." }
    } finally {
        Pop-Location
    }
} else {
    Write-Host "Web interface is up to date."
}

# ---------------------------------------------------------------- 3. Start
$port = $Port
$lastPort = $Port + 10
while ($port -le $lastPort -and -not (Test-PortFree $port)) {
    if (Test-OurApp $port) {
        Write-Step "The app is already running at http://127.0.0.1:$port"
        if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$port" }
        exit 0
    }
    $port++
}
if ($port -gt $lastPort) { Stop-WithError "Ports $Port-$lastPort are all busy. Close other programs and try again." }

$url = "http://127.0.0.1:$port"
Write-Step "Starting the app at $url"
Write-Host "Keep this window open while you use the app. Close it (or press Ctrl+C) to stop." -ForegroundColor Yellow
Write-Host "Uploaded files and generated certificates are deleted when the app stops."

if (-not $NoBrowser) {
    Start-Job -ArgumentList $url -ScriptBlock {
        param($u)
        for ($i = 0; $i -lt 120; $i++) {
            try { Invoke-RestMethod "$u/api/health" -TimeoutSec 2 | Out-Null; Start-Process $u; return } catch { Start-Sleep -Milliseconds 500 }
        }
    } | Out-Null
}

Set-Location -LiteralPath $Backend
& $VenvPy -m uvicorn app.main:app --host 127.0.0.1 --port $port
