# Start Redis (Docker) then run the one-shot parallel pipeline from project root.
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker not found. Install Docker Desktop or start Redis on port 6379 manually."
    exit 1
}
docker compose up -d
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python main.py @args
exit $LASTEXITCODE
