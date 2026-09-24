$ErrorActionPreference = "Stop"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    Write-Error "Chưa có .venv. Chạy .\\setup_windows.ps1 trước."
}
& .\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
