param(
    [Parameter(Mandatory = $true)]
    [string]$Url
)

$ErrorActionPreference = 'Stop'
try {
    $workbenchUri = [Uri]$Url
} catch {
    throw 'Url must be a complete HTTPS origin.'
}
if (
    -not $workbenchUri.IsAbsoluteUri -or
    $workbenchUri.Scheme -ne 'https' -or
    -not [string]::IsNullOrEmpty($workbenchUri.UserInfo) -or
    $workbenchUri.AbsolutePath -ne '/' -or
    -not [string]::IsNullOrEmpty($workbenchUri.Query) -or
    -not [string]::IsNullOrEmpty($workbenchUri.Fragment)
) {
    throw 'Url must be a complete HTTPS origin without a path, query, fragment, or credentials.'
}

$hermesScripts = Join-Path $env:LOCALAPPDATA 'hermes\hermes-agent\venv\Scripts'
$hermesPython = Join-Path $hermesScripts 'python.exe'
$hermesCommand = Join-Path $hermesScripts 'hermes.exe'
$connector = Join-Path $PSScriptRoot 'hermes_cloud_connector.py'
$logDirectory = Join-Path $env:LOCALAPPDATA 'PersonalWorkbench\logs'
$logPath = Join-Path $logDirectory 'hermes-cloud-connector.log'
$previousLogPath = Join-Path $logDirectory 'hermes-cloud-connector.previous.log'

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
if (Test-Path -LiteralPath $logPath) {
    $logFile = Get-Item -LiteralPath $logPath
    if ($logFile.Length -gt 5MB) {
        Move-Item -LiteralPath $logPath -Destination $previousLogPath -Force
    }
}

if (-not (Test-Path -LiteralPath $hermesPython)) {
    throw 'Hermes Python runtime is not installed.'
}
if (-not (Test-Path -LiteralPath $hermesCommand)) {
    throw 'Hermes command is not installed.'
}
if (-not (Test-Path -LiteralPath $connector)) {
    throw 'Hermes cloud connector script is missing.'
}

& $hermesPython $connector --url $Url --hermes-command $hermesCommand *>> $logPath
exit $LASTEXITCODE
