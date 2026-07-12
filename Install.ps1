# NDC Installer — Nexus Download Collection
# https://github.com/SahiDemon/NCD

$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'

function Write-Banner {
    Clear-Host
    Write-Host ""
    Write-Host "  =========================================" -ForegroundColor Cyan
    Write-Host "         N E X U S   M O D S   N D C" -ForegroundColor Cyan
    Write-Host "  =========================================" -ForegroundColor Cyan
    Write-Host "  Nexus Download Collection  —  Installer" -ForegroundColor White
    Write-Host "  by SahiDemon" -ForegroundColor DarkCyan
    Write-Host ""
    Write-Host "  -----------------------------------------" -ForegroundColor DarkGray
    Write-Host ""
}

function Write-Step($n, $text) {
    Write-Host "  [$n] $text" -ForegroundColor Yellow
}

function Write-OK($text) {
    Write-Host "  [+] $text" -ForegroundColor Green
}

function Write-Warn($text) {
    Write-Host "  [!] $text" -ForegroundColor DarkYellow
}

function Write-Err($text) {
    Write-Host "  [x] $text" -ForegroundColor Red
}

# ── Banner ────────────────────────────────────────────────────────────────────
Write-Banner

# ── Step 1: Pick install folder ───────────────────────────────────────────────
Write-Step 1 "Setting up install folder"

$defaultFolder = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "NDC"
Write-Host "  Where would you like to install NDC?" -ForegroundColor White
Write-Host "  Default: $defaultFolder" -ForegroundColor DarkGray
Write-Host "  (Press Enter to use default, or type a custom path)" -ForegroundColor DarkGray
Write-Host ""
$userPath = Read-Host "  Install path"
if ([string]::IsNullOrWhiteSpace($userPath)) {
    $TargetFolder = $defaultFolder
} else {
    $TargetFolder = $userPath.Trim()
}

if (-not (Test-Path $TargetFolder)) {
    New-Item -ItemType Directory -Force -Path $TargetFolder | Out-Null
    Write-OK "Created folder: $TargetFolder"
} else {
    Write-Warn "Folder already exists, updating files inside it."
}
Write-Host ""

# ── Step 2: Download files ────────────────────────────────────────────────────
Write-Step 2 "Downloading NDC from GitHub"

$hasGit = $false
try { $null = Get-Command git -ErrorAction Stop; $hasGit = $true } catch {}

if ($hasGit) {
    Write-Host "  Git found — cloning repository..." -ForegroundColor DarkGray
    Push-Location $TargetFolder
    git clone https://github.com/SahiDemon/NCD.git . 2>&1 | Out-Null
    Pop-Location
    Write-OK "Clone complete."
} else {
    Write-Host "  Git not found — downloading ZIP from GitHub..." -ForegroundColor DarkGray
    $zipUrl  = "https://github.com/SahiDemon/NCD/archive/refs/heads/main.zip"
    $zipFile = Join-Path $TargetFolder "NCD-main.zip"
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipFile
    Expand-Archive -Path $zipFile -DestinationPath $TargetFolder -Force
    $subFolder = Join-Path $TargetFolder "NCD-main"
    if (Test-Path $subFolder) {
        Get-ChildItem -Path $subFolder | Move-Item -Destination $TargetFolder -Force
        Remove-Item $subFolder -Recurse -Force
    }
    Remove-Item $zipFile -Force
    Write-OK "Download and extraction complete."
}
Write-Host ""

# ── Step 3: Done ──────────────────────────────────────────────────────────────
Write-Step 3 "Launching NDC"
Write-Host ""
Write-Host "  NDC is ready! The first-time setup will run inside the app." -ForegroundColor White
Write-Host "  (asking for your mode choice, API key, and cookies if needed)" -ForegroundColor DarkGray
Write-Host "  -----------------------------------------" -ForegroundColor DarkGray
Write-Host ""

Start-Sleep -Seconds 1
Start-Process -FilePath (Join-Path $TargetFolder "Run NDC.bat") -WorkingDirectory $TargetFolder
