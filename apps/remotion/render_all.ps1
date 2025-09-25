# This script renders all clips prepared by the Python script.

# Exit immediately if a command exits with a non-zero status.
$ErrorActionPreference = "Stop"

Write-Host "--- Starting Batch Remotion Rendering ---"

# Define paths relative to this script's location (apps/remotion)
$ProjectRoot = "../.."
$PublicDir = ".\public"
$RenderedDir = "$ProjectRoot\rendered"
$PropsDir = "$PublicDir\props"


# Load optional overrides from .env (e.g. REMOTION_CHROMIUM_EXECUTABLE)
$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path $EnvFile) {
    try {
        foreach ($line in Get-Content -Path $EnvFile -Encoding UTF8) {
            if ([string]::IsNullOrWhiteSpace($line) -or $line.TrimStart().StartsWith('#')) {
                continue
            }
            $pair = $line -split '=', 2
            if ($pair.Length -ne 2) { continue }
            $key = $pair[0].Trim()
            $value = $pair[1].Trim()
            if (-not $value) { continue }
            switch ($key) {
                'REMOTION_CHROMIUM_EXECUTABLE' {
                    $resolved = Resolve-Path -Path $value -ErrorAction SilentlyContinue
                    if ($resolved) {
                        $env:REMOTION_CHROMIUM_EXECUTABLE = $resolved.Path
                    }
                }
                'REMOTION_BROWSER_TIMEOUT_MS' {
                    $env:REMOTION_BROWSER_TIMEOUT_MS = $value
                }
            }
        }
    } catch {
        Write-Warning "Could not read .env overrides: $_"
    }
}

if (-not $env:REMOTION_BROWSER_TIMEOUT_MS) {
    $env:REMOTION_BROWSER_TIMEOUT_MS = "120000"
}

# Determine which video directory to use (optimized or original)
$OptimizedVideosDir = "$PublicDir\re_encoded_clips"
$OriginalVideosDir = "$PublicDir\out_clips"

$VideoDirToRender = ""
if (Test-Path $OptimizedVideosDir) {
    $VideoDirToRender = $OptimizedVideosDir
    Write-Host "Found optimized videos. Rendering from: $OptimizedVideosDir"
} else {
    $VideoDirToRender = $OriginalVideosDir
    Write-Host "Optimized videos not found. Rendering from original clips: $OriginalVideosDir"
}

# Get all video files to be rendered
$videoFiles = Get-ChildItem -Path $VideoDirToRender -Filter "clip_*.mp4"

if (-not $videoFiles) {
    Write-Host "No .mp4 clips found in $VideoDirToRender. Exiting."
    exit
}

# Remove legacy temp dir inside public if present

$LegacyPublicTemp = Join-Path $PublicDir "remotion_tmp"

if (Test-Path $LegacyPublicTemp) {

    Remove-Item -Path $LegacyPublicTemp -Recurse -Force -ErrorAction SilentlyContinue

}

# Prepare dedicated temp directory for Remotion to avoid AppData race conditions
$RemotionTempDir = Join-Path $ProjectRoot "remotion_tmp"
if (Test-Path $RemotionTempDir) {
    Get-ChildItem -Path $RemotionTempDir -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
} else {
    New-Item -ItemType Directory -Path $RemotionTempDir | Out-Null
}
$AbsoluteTempDir = (Resolve-Path $RemotionTempDir).Path
$OriginalTemp = $env:TEMP
$OriginalTmp = $env:TMP
$OriginalRemotionTmp = $env:REMOTION_TMPDIR
$env:TEMP = $AbsoluteTempDir
$env:TMP = $AbsoluteTempDir
$env:REMOTION_TMPDIR = $AbsoluteTempDir
try {
    # Loop through each video and render it
    foreach ($videoFile in $videoFiles) {
        $baseName = $videoFile.BaseName
        $propsPath = "$PropsDir\${baseName}.json"

        Write-Host "`nProcessing $($videoFile.Name)..."

        if (-not (Test-Path $propsPath)) {
            Write-Warning "Props file not found for $($videoFile.Name) at $propsPath. Skipping."
            continue
        }

        $outputFile = "$RenderedDir\rendered_$($videoFile.Name)"

        $cmdArray = @(
            "npx",
            "remotion",
            "render",
            "src/index.tsx",
            "VideoWithBands",
            $outputFile,
            "--props",
            $propsPath,
            "--timeout",
            $env:REMOTION_BROWSER_TIMEOUT_MS
        )

        if ($env:REMOTION_CHROMIUM_EXECUTABLE) {
            $cmdArray += @("--chromium-executable", $env:REMOTION_CHROMIUM_EXECUTABLE)
        }
        $cmdString = $cmdArray -join ' '
        Write-Host "  -> Running command: $cmdString"
        cmd /c $cmdString

        if ($LASTEXITCODE -ne 0) {
            Write-Error "  -> ERROR: Remotion rendering failed for $($videoFile.Name) with exit code $LASTEXITCODE. Please review the output from Remotion above."
        } else {
            Write-Host "  -> Successfully rendered: $outputFile" -ForegroundColor Green
        }
    }
    Write-Host "`n--- Batch Remotion Rendering Complete ---"
} finally {
    $env:TEMP = $OriginalTemp
    $env:TMP = $OriginalTmp
    if ($null -ne $OriginalRemotionTmp) {
        $env:REMOTION_TMPDIR = $OriginalRemotionTmp
    } else {
        Remove-Item Env:REMOTION_TMPDIR -ErrorAction SilentlyContinue
    }
    if (Test-Path $RemotionTempDir) {
        Remove-Item -Path $RemotionTempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
