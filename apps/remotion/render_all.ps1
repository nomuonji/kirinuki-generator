# This script renders all clips prepared by the Python script.

# Exit immediately if a command exits with a non-zero status.
$ErrorActionPreference = "Stop"

Write-Host "--- Starting Batch Remotion Rendering ---"

# Define paths relative to this script's location (apps/remotion)
$ProjectRoot = "../.."
$PublicDir = ".\public"
$RenderedDir = "$ProjectRoot\rendered"
$PropsDir = "$PublicDir\props"

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

# Loop through each video and render it
foreach ($videoFile in $videoFiles) {
    $baseName = $videoFile.BaseName
    $propsFile = "$PropsDir\${baseName}.json"

    Write-Host "`nProcessing $($videoFile.Name)..."

    if (-not (Test-Path $propsFile)) {
        Write-Warning "Props file not found for $($videoFile.Name) at $propsFile. Skipping."
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
        $propsFile
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
