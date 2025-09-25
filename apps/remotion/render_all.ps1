# This script renders all clips prepared by the Python script.

# Exit immediately if a command exits with a non-zero status.
$ErrorActionPreference = "Stop"

Write-Host "--- Starting Batch Remotion Rendering ---"

# Define paths relative to this script's location (apps/remotion)
$ProjectRoot = "../.."
$PublicDir = ".\public"
$RenderedDir = "$ProjectRoot\rendered"
$PropsDir = "$PublicDir\props"
$StyledPropsDir = "$PublicDir\styled_props"

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
        $propsFilePlain = "$PropsDir\${baseName}.json"
        $propsFileStyled = "$StyledPropsDir\${baseName}.json"
        $propsForRender = if (Test-Path $propsFileStyled) { $propsFileStyled } else { $propsFilePlain }

        Write-Host "`nProcessing $($videoFile.Name)..."

        if (-not (Test-Path $propsForRender)) {
            Write-Warning "Props file not found for $($videoFile.Name) at $propsForRender. Skipping."
            continue
        }

        if (($propsForRender -ne $propsFilePlain) -and -not (Test-Path $propsFilePlain)) {
            Write-Warning "Plain props not found for $($videoFile.Name). Rendering will use styled props only."
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
            $propsForRender,
            "--timeout",
            "90000"
        )

        # Join the array into a single string to be executed
        $cmdString = $cmdArray -join ' '
        Write-Host "  -> Running command: $cmdString"
        
        # Execute the command via cmd.exe to ensure npx is found, similar to shell=True
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
