# Install & Launch NDC (Nexus Download Collection)
# This script sets up NDC on a fresh PC. It works even if Git is not installed.

$ProgressPreference = 'SilentlyContinue'

$TargetFolder = Join-Path $PWD "NCD"
if (Test-Path $TargetFolder) {
    Write-Host "[-] Directory $TargetFolder already exists. Using existing folder." -ForegroundColor Yellow
} else {
    New-Item -ItemType Directory -Force -Path $TargetFolder | Out-Null
}

Set-Location $TargetFolder

# Check if git is installed
$hasGit = $false
try {
    $null = Get-Command git -ErrorAction Stop
    $hasGit = $true
} catch {}

if ($hasGit) {
    Write-Host "[+] Git detected. Cloning repository..." -ForegroundColor Cyan
    git clone https://github.com/SahiDemon/NCD.git .
} else {
    Write-Host "[+] Git not detected. Downloading source ZIP from GitHub..." -ForegroundColor Cyan
    
    $zipUrl = "https://github.com/SahiDemon/NCD/archive/refs/heads/main.zip"
    $zipFile = Join-Path $TargetFolder "NCD-main.zip"
    
    # Download the ZIP
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipFile
    
    # Extract the files
    Write-Host "[+] Extracting files..." -ForegroundColor Cyan
    Expand-Archive -Path $zipFile -DestinationPath $TargetFolder -Force
    
    # Move files out of the NCD-main subfolder
    $subFolder = Join-Path $TargetFolder "NCD-main"
    if (Test-Path $subFolder) {
        Get-ChildItem -Path $subFolder | Move-Item -Destination $TargetFolder -Force
        Remove-Item $subFolder -Recurse -Force
    }
    
    # Clean up zip
    Remove-Item $zipFile -Force
}

Write-Host "[+] Setup complete. Launching NDC..." -ForegroundColor Green
Start-Process -FilePath "Run NDC.bat" -WorkingDirectory $TargetFolder
