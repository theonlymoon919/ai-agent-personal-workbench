param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('meal', 'weight', 'exercise')]
    [string]$Kind,
    [Parameter(Mandatory = $true)]
    [string]$FilePath,
    [string]$RecordDate = (Get-Date -Format 'yyyy-MM-dd'),
    [ValidateSet('', 'breakfast', 'lunch', 'afternoon_tea', 'dinner', 'snack', 'late_night')]
    [string]$MealSlot = ''
)

$ErrorActionPreference = 'Stop'
$runtimeRoot = Join-Path $env:LOCALAPPDATA 'PersonalWorkbench'
$hermesPython = Join-Path $env:LOCALAPPDATA 'hermes\hermes-agent\venv\Scripts\python.exe'
$uploader = Join-Path $runtimeRoot 'hermes_upload_health_image.py'

foreach ($requiredPath in @($hermesPython, $uploader)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Hermes health-image upload component is missing. Re-run the Personal Workbench Hermes installer."
    }
}

$arguments = @($uploader, '--kind', $Kind, '--file', $FilePath, '--record-date', $RecordDate)
if ($MealSlot) {
    $arguments += @('--meal-slot', $MealSlot)
}
& $hermesPython @arguments
if ($LASTEXITCODE -ne 0) {
    throw 'Hermes health-image upload failed.'
}
