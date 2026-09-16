$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$ArgumentList
    )
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE."
    }
}

Write-Host "Setting up LinePulse AI..." -ForegroundColor Cyan

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            Invoke-Checked -FilePath "py" -ArgumentList @("-3.12", "-m", "venv", ".venv")
        }
        catch {
            Write-Host "Python Launcher could not create the environment. Trying uv..." -ForegroundColor Yellow
        }
    }

    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
            throw "Python 3.12 or uv is required. Install Python 3.12, then run this script again."
        }
        $python312 = (& uv python find 3.12).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $python312) {
            throw "uv could not locate Python 3.12."
        }
        Invoke-Checked -FilePath $python312 -ArgumentList @("-m", "venv", ".venv")
    }
}

$python = Resolve-Path ".venv\Scripts\python.exe"
Invoke-Checked -FilePath $python -ArgumentList @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Checked -FilePath $python -ArgumentList @("-m", "pip", "install", "-e", ".")

$env:PYTHONPATH = "$PWD\src"
Invoke-Checked -FilePath $python -ArgumentList @("scripts\train_model.py")
Invoke-Checked -FilePath $python -ArgumentList @("-m", "unittest", "discover", "-s", "tests", "-v")

Write-Host "LinePulse AI is ready. Run .\run_app.ps1" -ForegroundColor Green
