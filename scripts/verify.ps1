$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

function Assert-LastExit([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating a Python 3.12 virtual environment..." -ForegroundColor Cyan

    $created = $false
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & py -3.12 -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 12))" 2>$null
        if ($LASTEXITCODE -eq 0) {
            & py -3.12 -m venv .venv
            Assert-LastExit "Virtual-environment creation"
            $created = $true
        }
    }

    # Enterprise Windows policies can prevent uv from creating its command
    # trampoline even when uv successfully downloaded CPython. Use that real
    # interpreter directly if the Python launcher does not see it.
    if (-not $created) {
        $uvPythonRoot = Join-Path $env:APPDATA "uv\python"
        $uvPython = Get-ChildItem `
            -Path (Join-Path $uvPythonRoot "cpython-3.12*-windows-x86_64-none\python.exe") `
            -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($uvPython) {
            & $uvPython.FullName -m venv .venv
            Assert-LastExit "Virtual-environment creation from uv CPython"
            $created = $true
        }
    }

    if (-not $created) {
        throw "Python 3.12 was not found. Install it, then run this script again."
    }
}

if (-not (Test-Path $venvPython)) {
    throw "The .venv was not created correctly. Delete only the incomplete .venv folder, install Python 3.12, and rerun this script."
}

$env:PYTHONPATH = Join-Path $projectRoot "src"

Write-Host "Installing LinePulse AI dependencies..." -ForegroundColor Cyan
& $venvPython -m pip install -e .
Assert-LastExit "Dependency installation"

Write-Host "Training the degradation model..." -ForegroundColor Cyan
& $venvPython scripts\train_model.py
Assert-LastExit "Model training"

Write-Host "Running automated tests..." -ForegroundColor Cyan
& $venvPython -m unittest discover -s tests -v
Assert-LastExit "Automated tests"

Write-Host "Running the smoke test..." -ForegroundColor Cyan
& $venvPython scripts\smoke_test.py
Assert-LastExit "Smoke test"

Write-Host "Running the demo preflight..." -ForegroundColor Cyan
& $venvPython scripts\demo_preflight.py
Assert-LastExit "Demo preflight"

Write-Host "LinePulse AI is verified and ready to start." -ForegroundColor Green
Write-Host "API:       .\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000"
Write-Host "Dashboard: .\.venv\Scripts\python.exe -m streamlit run dashboard\app.py"
