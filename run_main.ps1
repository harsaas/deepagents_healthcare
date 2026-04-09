param(
    [Parameter(Mandatory = $false)]
    [string]$PatientId,

    [Parameter(Mandatory = $false)]
    [string]$Query
)

$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Could not find venv python at: $python`nCreate a venv in .venv or update this script."
}

if (-not $PatientId) {
    $PatientId = Read-Host "Enter patient_id"
}
if (-not $PatientId) {
    throw "patient_id cannot be empty"
}

if (-not $Query) {
    $Query = Read-Host "Enter your question/request"
}
if (-not $Query) {
    throw "query cannot be empty"
}

& $python -m scripts.main --patient-id $PatientId --query $Query
