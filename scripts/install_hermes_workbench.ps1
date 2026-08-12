param(
    [string]$WorkbenchUrl = $env:PERSONAL_WORKBENCH_URL,
    [string]$McpUrl = '',
    [string]$TaskName = 'Personal Workbench Hermes Cloud Connector',
    [switch]$ReuseExistingConnection,
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$hermesScripts = Join-Path $env:LOCALAPPDATA 'hermes\hermes-agent\venv\Scripts'
$hermesPython = Join-Path $hermesScripts 'python.exe'
$hermesCommand = Join-Path $hermesScripts 'hermes.exe'
$configureScript = Join-Path $PSScriptRoot 'configure_hermes.py'
$startScript = Join-Path $PSScriptRoot 'start_hermes_cloud_connector.ps1'
$connectorScript = Join-Path $PSScriptRoot 'hermes_cloud_connector.py'
$uploadPythonScript = Join-Path $PSScriptRoot 'hermes_upload_health_image.py'
$uploadPowerShellScript = Join-Path $PSScriptRoot 'upload_health_image.ps1'
$assetInstaller = Join-Path $PSScriptRoot 'install_hermes_assets.py'
$projectRoot = Split-Path $PSScriptRoot -Parent
$skillSource = Join-Path $projectRoot 'hermes\personal-workbench'
$operatingRules = Join-Path $projectRoot 'docs\HERMES_WORKBENCH_PROMPT.md'

foreach ($requiredPath in @(
    $hermesPython,
    $hermesCommand,
    $configureScript,
    $startScript,
    $connectorScript,
    $uploadPythonScript,
    $uploadPowerShellScript,
    $assetInstaller,
    (Join-Path $skillSource 'SKILL.md'),
    $operatingRules
)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required file is missing: $requiredPath"
    }
}

if ($ValidateOnly) {
    Write-Host 'Hermes workbench package validation passed.'
    exit 0
}

if ([string]::IsNullOrWhiteSpace($WorkbenchUrl)) {
    throw 'Pass -WorkbenchUrl https://workbench.example.com or set PERSONAL_WORKBENCH_URL.'
}
$WorkbenchUrl = $WorkbenchUrl.TrimEnd('/')
try {
    $workbenchUri = [Uri]$WorkbenchUrl
} catch {
    throw 'WorkbenchUrl must be a complete HTTPS origin.'
}
if (
    -not $workbenchUri.IsAbsoluteUri -or
    $workbenchUri.Scheme -ne 'https' -or
    -not [string]::IsNullOrEmpty($workbenchUri.UserInfo) -or
    $workbenchUri.AbsolutePath -ne '/' -or
    -not [string]::IsNullOrEmpty($workbenchUri.Query) -or
    -not [string]::IsNullOrEmpty($workbenchUri.Fragment)
) {
    throw 'WorkbenchUrl must be a complete HTTPS origin without a path, query, fragment, or credentials.'
}
if ([string]::IsNullOrWhiteSpace($McpUrl)) {
    $McpUrl = "$WorkbenchUrl/mcp/"
}
try {
    $mcpUri = [Uri]$McpUrl
} catch {
    throw 'McpUrl must be a complete HTTPS URL ending in /mcp/.'
}
if (
    -not $mcpUri.IsAbsoluteUri -or
    $mcpUri.Scheme -ne 'https' -or
    -not [string]::IsNullOrEmpty($mcpUri.UserInfo) -or
    $mcpUri.Authority -ne $workbenchUri.Authority -or
    $mcpUri.AbsolutePath.TrimEnd('/') -ne '/mcp' -or
    -not [string]::IsNullOrEmpty($mcpUri.Query) -or
    -not [string]::IsNullOrEmpty($mcpUri.Fragment)
) {
    throw 'McpUrl must use the same HTTPS origin and end in /mcp/.'
}

$runtimeRoot = Join-Path $env:LOCALAPPDATA 'PersonalWorkbench'
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
Copy-Item -LiteralPath $uploadPythonScript -Destination (Join-Path $runtimeRoot 'hermes_upload_health_image.py') -Force
Copy-Item -LiteralPath $uploadPowerShellScript -Destination (Join-Path $runtimeRoot 'upload_health_image.ps1') -Force
Copy-Item -LiteralPath $connectorScript -Destination (Join-Path $runtimeRoot 'hermes_cloud_connector.py') -Force
Copy-Item -LiteralPath $startScript -Destination (Join-Path $runtimeRoot 'start_hermes_cloud_connector.ps1') -Force
Copy-Item -LiteralPath $operatingRules -Destination (Join-Path $runtimeRoot 'HERMES_WORKBENCH_PROMPT.md') -Force

if ($ReuseExistingConnection) {
    Write-Host 'Reusing the existing personal_workbench MCP and private token configuration.'
} else {
    Write-Host 'Configuring personal_workbench MCP. Paste the private Hermes Agent Token at the hidden prompt.'
    & $hermesPython $configureScript --url $McpUrl
    if ($LASTEXITCODE -ne 0) {
        throw 'Hermes MCP configuration failed.'
    }
}

$assetArguments = @(
    $assetInstaller,
    '--source-skill-root', $skillSource,
    '--operating-rules', $operatingRules
)
if ($ReuseExistingConnection) {
    $assetArguments += '--require-existing-connection'
}
& $hermesPython @assetArguments
if ($LASTEXITCODE -ne 0) {
    throw 'Hermes personal-workbench skill installation failed.'
}

$powerShell = Join-Path $PSHOME 'powershell.exe'
if (-not (Test-Path -LiteralPath $powerShell)) {
    $powerShell = 'powershell.exe'
}
$runtimeStartScript = Join-Path $runtimeRoot 'start_hermes_cloud_connector.ps1'
$actionArguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -Url "{1}"' -f $runtimeStartScript, $WorkbenchUrl
$action = New-ScheduledTaskAction -Execute $powerShell -Argument $actionArguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 10 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description 'Keep the current user Hermes connected to Personal Workbench cloud jobs.' `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Host ''
Write-Host 'Configuration complete: MCP, persistent skill, image bridge, and cloud connector are installed.'
Write-Host 'Restart Hermes so normal chat sessions reload the skill and attachment handoff rules.'
Write-Host "Scheduled task: $TaskName"
Write-Host "Connector log: $(Join-Path $env:LOCALAPPDATA 'PersonalWorkbench\logs\hermes-cloud-connector.log')"
