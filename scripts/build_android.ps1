param(
    [switch]$SkipSdkInstall
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$mobileRoot = Join-Path $projectRoot 'mobile'
$buildRoot = Join-Path $projectRoot 'build\android'
$sdkRoot = Join-Path $buildRoot 'sdk'
$toolsRoot = Join-Path $sdkRoot 'cmdline-tools\latest'
$sdkManager = Join-Path $toolsRoot 'bin\sdkmanager.bat'
$gradleVersion = '8.11.1'
$gradleRoot = Join-Path $buildRoot "gradle-$gradleVersion"
$gradle = Join-Path $gradleRoot 'bin\gradle.bat'

$javaCommand = Get-Command java.exe -ErrorAction SilentlyContinue
if (-not $javaCommand) {
    $jdk = Get-ChildItem (Join-Path $env:ProgramFiles 'Microsoft') -Directory -Filter 'jdk-17*' -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
    if ($jdk) {
        $env:JAVA_HOME = $jdk.FullName
        $env:Path = (Join-Path $jdk.FullName 'bin') + ';' + $env:Path
        $javaCommand = Get-Command java.exe -ErrorAction SilentlyContinue
    }
}
if (-not $javaCommand) {
    throw 'JDK 17 is required. Install Microsoft.OpenJDK.17 with winget.'
}
if (-not $env:JAVA_HOME) {
    $env:JAVA_HOME = Split-Path -Parent (Split-Path -Parent $javaCommand.Source)
}

New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null

if (-not (Test-Path -LiteralPath $sdkManager)) {
    if ($SkipSdkInstall) { throw 'Android SDK command-line tools are missing.' }
    $toolsZip = Join-Path $buildRoot 'commandlinetools-win.zip'
    $toolsExtract = Join-Path $buildRoot 'commandlinetools-extract'
    if (-not (Test-Path -LiteralPath $toolsZip)) {
        Invoke-WebRequest -Uri 'https://dl.google.com/android/repository/commandlinetools-win-15859902_latest.zip' -OutFile $toolsZip
    }
    $actualHash = (Get-FileHash -LiteralPath $toolsZip -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne '90ae805d20434428bffcb699c290860f19bb5f66a67e6b330067e3de801fb04a') {
        throw 'Android command-line tools checksum did not match.'
    }
    $resolvedExtract = [IO.Path]::GetFullPath($toolsExtract)
    $resolvedBuildRoot = [IO.Path]::GetFullPath($buildRoot)
    if (-not $resolvedExtract.StartsWith($resolvedBuildRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Invalid Android extraction path.'
    }
    if (Test-Path -LiteralPath $toolsExtract) {
        Remove-Item -LiteralPath $toolsExtract -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $toolsExtract, (Split-Path -Parent $toolsRoot) | Out-Null
    & tar.exe -xf $toolsZip -C $toolsExtract
    if ($LASTEXITCODE -ne 0) { throw "Android tools extraction failed with exit code $LASTEXITCODE." }
    Move-Item -LiteralPath (Join-Path $toolsExtract 'cmdline-tools') -Destination $toolsRoot
}

$env:ANDROID_HOME = $sdkRoot
$env:ANDROID_SDK_ROOT = $sdkRoot
if (-not $SkipSdkInstall) {
    (1..30 | ForEach-Object { 'y' }) | & $sdkManager --licenses | Out-Null
    & $sdkManager 'platform-tools' 'platforms;android-35' 'build-tools;35.0.0'
    if ($LASTEXITCODE -ne 0) { throw "sdkmanager failed with exit code $LASTEXITCODE." }
}

if (-not (Test-Path -LiteralPath $gradle)) {
    $gradleZip = Join-Path $buildRoot "gradle-$gradleVersion-bin.zip"
    Invoke-WebRequest -Uri "https://services.gradle.org/distributions/gradle-$gradleVersion-bin.zip" -OutFile $gradleZip
    Expand-Archive -LiteralPath $gradleZip -DestinationPath $buildRoot -Force
}

Push-Location $mobileRoot
try {
    & $gradle --no-daemon clean assembleDebug
    if ($LASTEXITCODE -ne 0) { throw "Gradle failed with exit code $LASTEXITCODE." }
} finally {
    Pop-Location
}

$builtApk = Join-Path $mobileRoot 'app\build\outputs\apk\debug\app-debug.apk'
if (-not (Test-Path -LiteralPath $builtApk)) {
    throw 'Android APK was not created.'
}
Write-Host "Android debug APK created: $builtApk" -ForegroundColor Green
