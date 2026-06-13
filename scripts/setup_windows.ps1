param(
    [switch]$SkipModels,
    [switch]$SkipDoctor,
    [switch]$Force,
    [switch]$NoWinget,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch {
    # Best-effort only. Older PowerShell hosts can ignore this.
}

function Show-Help {
    Write-Host @"
meeting_record Windows setup helper

Usage:
  setup.bat
  setup.bat --skip-models
  setup.bat --skip-doctor
  setup.bat --no-winget

PowerShell:
  powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
  powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -SkipModels

What it does:
  1. Checks Python 3.10+
  2. Creates .env from .env.example if missing
  3. Creates .venv-meetingrec
  4. Installs Python packages
  5. Registers editable CLI commands
  6. Offers ffmpeg/Ollama winget install if missing
  7. Offers Ollama model pull and local AI model download
  8. Runs doctor.py

Options:
  --skip-models   Do not run scripts\download_models.py
  --skip-doctor   Do not run doctor.py at the end
  --force         Answer yes to setup prompts
  --no-winget     Do not offer winget installs
  --help          Show this help
"@
}

if ($Help) {
    Show-Help
    exit 0
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-WarnLine {
    param([string]$Message)
    Write-Host "[warn] $Message" -ForegroundColor Yellow
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[ok] $Message" -ForegroundColor Green
}

function Test-CommandAvailable {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Confirm-YesNo {
    param(
        [string]$Message,
        [bool]$DefaultYes = $true
    )

    if ($Force) {
        Write-Host "$Message yes (--force)"
        return $true
    }

    $hint = if ($DefaultYes) { "[Y/n]" } else { "[y/N]" }
    while ($true) {
        $answer = Read-Host "$Message $hint"
        if ([string]::IsNullOrWhiteSpace($answer)) {
            return $DefaultYes
        }
        switch ($answer.Trim().ToLowerInvariant()) {
            "y" { return $true }
            "yes" { return $true }
            "n" { return $false }
            "no" { return $false }
            default { Write-Host "Please answer y or n." }
        }
    }
}

function Invoke-Checked {
    param(
        [string]$File,
        [string[]]$Arguments
    )

    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $File $($Arguments -join ' ')"
    }
}

function Get-PythonExe {
    if (Test-CommandAvailable "py") {
        $probe = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $probe) {
            return ($probe | Select-Object -First 1).Trim()
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return $python.Source
    }

    return $null
}

function Assert-PythonVersion {
    param([string]$PythonExe)

    $versionText = & $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0 -or -not $versionText) {
        throw "Python exists but could not run. Install Python 3.10+ from https://python.org"
    }

    $version = [Version](($versionText | Select-Object -First 1).Trim())
    if ($version -lt [Version]"3.10") {
        throw "Python $version is too old. Install Python 3.10+ from https://python.org"
    }

    Write-Ok "Python $version detected: $PythonExe"
}

function Get-DotEnvValue {
    param(
        [string]$Name,
        [string]$DefaultValue
    )

    $envPath = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path $envPath)) {
        return $DefaultValue
    }

    foreach ($line in Get-Content $envPath) {
        $trimmed = $line.Trim()
        if ($trimmed -eq "" -or $trimmed.StartsWith("#")) {
            continue
        }
        $idx = $trimmed.IndexOf("=")
        if ($idx -lt 1) {
            continue
        }
        $key = $trimmed.Substring(0, $idx).Trim()
        if ($key -ne $Name) {
            continue
        }
        $value = $trimmed.Substring($idx + 1).Trim()
        $value = $value.Trim('"').Trim("'")
        if ($value -eq "") {
            return $DefaultValue
        }
        return $value
    }

    return $DefaultValue
}

function Offer-WingetInstall {
    param(
        [string]$Label,
        [string]$PackageId
    )

    if ($NoWinget) {
        Write-WarnLine "$Label is missing. Skipping winget offer because --no-winget was used."
        return
    }
    if (-not (Test-CommandAvailable "winget")) {
        Write-WarnLine "$Label is missing, and winget is not available. Install it manually."
        return
    }
    if (-not (Confirm-YesNo "Install $Label with winget now?" $false)) {
        Write-WarnLine "$Label install skipped."
        return
    }

    & winget install --id $PackageId --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        Write-WarnLine "winget install failed for $Label. Install it manually, then open a new terminal."
    } else {
        Write-Ok "$Label install command finished. Open a new terminal if the command is still not found."
    }
}

Write-Host "meeting_record setup for Windows"
Write-Host "Project: $ProjectRoot"

Write-Step "Checking Python"
$PythonExe = Get-PythonExe
if (-not $PythonExe) {
    throw "Python 3.10+ was not found. Install it from https://python.org and run setup.bat again."
}
Assert-PythonVersion $PythonExe

Write-Step "Preparing local files"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Ok ".env created from .env.example"
} else {
    Write-Ok ".env already exists; leaving it unchanged"
}

foreach ($dir in @("data", "data\watch", "data\uploads", "data\work", "data\models")) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
    }
}
Write-Ok "data folders ready"

Write-Step "Creating Python virtual environment"
$VenvPython = Join-Path $ProjectRoot ".venv-meetingrec\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Invoke-Checked $PythonExe @("-m", "venv", ".venv-meetingrec")
    Write-Ok ".venv-meetingrec created"
} else {
    Write-Ok ".venv-meetingrec already exists"
}

Write-Step "Installing Python packages"
Invoke-Checked $VenvPython @("-m", "ensurepip", "--upgrade")
Invoke-Checked $VenvPython @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")
Invoke-Checked $VenvPython @("-m", "pip", "install", "-r", "requirements.txt")
Invoke-Checked $VenvPython @("-m", "pip", "install", "-e", ".", "--no-deps")
Write-Ok "Python packages installed"

Write-Step "Checking external tools"
if (-not (Test-CommandAvailable "ffmpeg")) {
    Offer-WingetInstall "ffmpeg" "Gyan.FFmpeg"
} else {
    Write-Ok "ffmpeg command found"
}

if (-not (Test-CommandAvailable "ollama")) {
    Offer-WingetInstall "Ollama" "Ollama.Ollama"
} else {
    Write-Ok "ollama command found"
}

if (Test-CommandAvailable "ollama") {
    $ollamaModel = Get-DotEnvValue "OLLAMA_MODEL" "gemma4:e2b-it-qat"
    try {
        $ollamaList = (& ollama list 2>$null | Out-String)
        if ($LASTEXITCODE -eq 0 -and $ollamaList -notmatch [regex]::Escape($ollamaModel)) {
            if (Confirm-YesNo "Pull Ollama model '$ollamaModel' now? This can take several GB." $true) {
                & ollama pull $ollamaModel
                if ($LASTEXITCODE -ne 0) {
                    Write-WarnLine "ollama pull failed. Start Ollama, then run: ollama pull $ollamaModel"
                }
            }
        } elseif ($LASTEXITCODE -eq 0) {
            Write-Ok "Ollama model appears to be installed: $ollamaModel"
        }
    } catch {
        Write-WarnLine "Could not query Ollama. Start Ollama, then run: ollama pull $ollamaModel"
    }
}

if ($SkipModels) {
    Write-WarnLine "Skipping local AI model download because --skip-models was used."
} elseif (Confirm-YesNo "Download local STT/speaker models now? Recommended; this can take several GB." $true) {
    Write-Step "Downloading local AI models"
    try {
        Invoke-Checked $VenvPython @("scripts\download_models.py")
        Write-Ok "Local AI model download finished"
    } catch {
        Write-WarnLine "Model download failed: $($_.Exception.Message)"
        Write-WarnLine "You can retry later with: .\.venv-meetingrec\Scripts\python.exe scripts\download_models.py"
    }
} else {
    Write-WarnLine "Local AI model download skipped. First transcription may download models later."
}

if ($SkipDoctor) {
    Write-WarnLine "Skipping doctor.py because --skip-doctor was used."
} else {
    Write-Step "Running doctor.py"
    & $VenvPython "doctor.py"
    if ($LASTEXITCODE -ne 0) {
        Write-WarnLine "doctor.py reported issues. Read the messages above, fix them, then run python doctor.py again."
    }
}

Write-Step "Done"
Write-Host "Next commands:"
Write-Host "  .\.venv-meetingrec\Scripts\Activate.ps1"
Write-Host "  python doctor.py"
Write-Host "  python main.py ""meeting.mp3"" --no-upload"
Write-Host ""
Write-Host "For folder watching:"
Write-Host "  python watcher.py"
