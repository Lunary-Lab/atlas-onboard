# Atlas Bootstrap - PowerShell Entrypoint
#
# $script = [System.Text.Encoding]::UTF8.GetString((Invoke-WebRequest -Uri "https://github.com/Lunary-Lab/atlas-onboard/releases/download/v0.1.0/bootstrap.ps1" -UseBasicParsing).Content); Invoke-Expression $script
#

$ErrorActionPreference = "Stop"

# --- Configuration ---
$APP_VERSION = "0.1.26"
$PAYLOAD_URL = "https://github.com/Lunary-Lab/atlas-onboard/releases/download/v0.3.17/payload.tar.gz"
$PAYLOAD_SHA256 = "7c8aaf68707d86f41d55968416af9810867df9bbb62e9910863b3e60360637a1"
# ---

function Write-Info {
    param([string]$Message)
    Write-Host "atlas-onboard: $Message" -ForegroundColor Cyan
}

function Write-Error {
    param([string]$Message)
    Write-Host "atlas-onboard: ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Test-Command {
    param([string]$Command)
    $null = Get-Command $Command -ErrorAction SilentlyContinue
    if (-not $?) {
        Write-Error "'$Command' is required but not found in PATH."
    }
}

function Get-Sha256Hash {
    param([string]$FilePath)
    $hash = Get-FileHash -Path $FilePath -Algorithm SHA256
    return $hash.Hash.ToLower()
}

function Main {
    # Check dependencies
    Test-Command "curl"
    
    # Determine cache directory
    $XDG_CACHE_HOME = if ($env:XDG_CACHE_HOME) { $env:XDG_CACHE_HOME } else { "$env:USERPROFILE\.cache" }
    $APP_CACHE_DIR = "$XDG_CACHE_HOME\atlas\bootstrap\$APP_VERSION"
    New-Item -ItemType Directory -Force -Path $APP_CACHE_DIR | Out-Null
    
    # Create temp directory
    $TMP_DIR = New-TemporaryFile | ForEach-Object { Remove-Item $_; New-Item -ItemType Directory -Path $_ }
    $PAYLOAD_PATH = "$TMP_DIR\payload.tar.gz"
    
    Write-Info "Downloading payload from $PAYLOAD_URL..."
    try {
        Invoke-WebRequest -Uri $PAYLOAD_URL -OutFile $PAYLOAD_PATH -UseBasicParsing
    } catch {
        Write-Error "Failed to download payload: $_"
    }
    
    Write-Info "Verifying payload checksum..."
    $CHECKSUM = Get-Sha256Hash -FilePath $PAYLOAD_PATH
    if ($CHECKSUM -ne $PAYLOAD_SHA256) {
        Write-Error "Checksum mismatch! Expected: $PAYLOAD_SHA256, Got: $CHECKSUM"
    }
    
    Write-Info "Extracting payload to $APP_CACHE_DIR..."
    # Use Windows tar (Windows 10 1903+), explicitly use System32 version to avoid WSL tar
    $windowsTar = "$env:SystemRoot\System32\tar.exe"
    if (Test-Path $windowsTar) {
        & $windowsTar -xzf $PAYLOAD_PATH -C $APP_CACHE_DIR
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to extract payload. tar exited with code $LASTEXITCODE"
        }
    } else {
        Write-Error "tar is required but not found at $windowsTar. Please ensure you're running Windows 10 1903+ or install Git for Windows."
    }
    
    Set-Location $APP_CACHE_DIR
    
    # Ensure XDG directories exist
    $XDG_DATA_HOME = if ($env:XDG_DATA_HOME) { $env:XDG_DATA_HOME } else { "$env:USERPROFILE\.local\share" }
    $XDG_CONFIG_HOME = if ($env:XDG_CONFIG_HOME) { $env:XDG_CONFIG_HOME } else { "$env:USERPROFILE\.config" }
    $XDG_CACHE_HOME = if ($env:XDG_CACHE_HOME) { $env:XDG_CACHE_HOME } else { "$env:USERPROFILE\.cache" }
    $XDG_STATE_HOME = if ($env:XDG_STATE_HOME) { $env:XDG_STATE_HOME } else { "$env:USERPROFILE\.local\state" }
    
    New-Item -ItemType Directory -Force -Path $XDG_DATA_HOME | Out-Null
    New-Item -ItemType Directory -Force -Path $XDG_CONFIG_HOME | Out-Null
    New-Item -ItemType Directory -Force -Path $XDG_CACHE_HOME | Out-Null
    New-Item -ItemType Directory -Force -Path $XDG_STATE_HOME | Out-Null
    
    # Add bin directory to PATH if dotfiles are not configured (dotfiles will handle PATH)
    $CONFIG_FILE = "$XDG_CONFIG_HOME\atlas\bootstrap.yaml"
    $shouldAddToPath = $true
    
    if (Test-Path $CONFIG_FILE) {
        # Check if dotfiles_repo is configured (not null or empty)
        $configContent = Get-Content $CONFIG_FILE -Raw
        if ($configContent -match 'dotfiles_repo:\s*(.+?)(?:\s|$)') {
            $dotfilesRepo = $matches[1].Trim().Trim('"').Trim("'")
            # Validate it's not null, empty, or just whitespace
            if ($dotfilesRepo -and $dotfilesRepo -ne "null" -and $dotfilesRepo -ne "~") {
                Write-Info "Dotfiles repository configured - skipping PATH modification (dotfiles will handle it)"
                $shouldAddToPath = $false
            }
        }
    }
    
    if ($shouldAddToPath) {
        $BIN_DIR = "$XDG_DATA_HOME\atlas\bin"
        New-Item -ItemType Directory -Force -Path $BIN_DIR | Out-Null
        
        $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
        if ($userPath -notlike "*$BIN_DIR*") {
            Write-Info "Adding Atlas bin directory to PATH..."
            [System.Environment]::SetEnvironmentVariable("Path", "$userPath;$BIN_DIR", "User")
            $env:Path = "$env:Path;$BIN_DIR"
            Write-Info "✅ Added $BIN_DIR to PATH"
        }
    }
    
    # Check for uv
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Info "Installing 'uv'..."
        $uvInstallScript = "$TMP_DIR\install-uv.ps1"
        Invoke-WebRequest -Uri "https://astral.sh/uv/install.ps1" -OutFile $uvInstallScript -UseBasicParsing
        & $uvInstallScript
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    }
    
    Write-Info "Creating Python virtual environment..."
    & uv venv
    
    Write-Info "Installing dependencies..."
    & uv pip sync requirements.lock
    
    Write-Info "Installing atlasonboard package..."
    & uv pip install -e .
    
    Write-Info "Starting Atlas Bootstrap application..."
    # Preserve environment variables (especially SB_BOOTSTRAP_CLIENT_SECRET)
    & .venv\Scripts\python.exe -m atlasonboard.cli run @args
    
    Write-Info "Cleaning up..."
    Remove-Item -Recurse -Force $TMP_DIR
    
    Write-Info "Done."
}

Main @args
