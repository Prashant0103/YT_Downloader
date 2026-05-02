# export_cookies.ps1
# Exports your YouTube cookies from Chrome into cookies.txt
# IMPORTANT: Close Chrome completely before running this script!
#
# Usage:  .\scripts\export_cookies.ps1

Write-Host "YouTube Cookie Exporter" -ForegroundColor Cyan
Write-Host "========================" -ForegroundColor Cyan
Write-Host ""
Write-Host "IMPORTANT: Close Chrome completely before proceeding!" -ForegroundColor Yellow
Write-Host "Press Enter when Chrome is closed, or Ctrl+C to cancel..."
$null = Read-Host

$ytdlp = Join-Path $PSScriptRoot "..\venv\Scripts\yt-dlp.exe"
$output = Join-Path $PSScriptRoot "..\cookies.txt"

if (-not (Test-Path $ytdlp)) {
    Write-Host "ERROR: yt-dlp not found at $ytdlp" -ForegroundColor Red
    Write-Host "Make sure your venv is activated and yt-dlp is installed."
    exit 1
}

Write-Host "Exporting cookies from Chrome..." -ForegroundColor Green
& $ytdlp --cookies-from-browser chrome --cookies $output --skip-download "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

if (Test-Path $output) {
    Write-Host ""
    Write-Host "SUCCESS: cookies.txt saved to $output" -ForegroundColor Green
    Write-Host "Restart the server to pick up the new cookies."
} else {
    Write-Host ""
    Write-Host "FAILED: cookies.txt was not created." -ForegroundColor Red
    Write-Host "Try the Chrome extension method instead:"
    Write-Host "  1. Install 'Get cookies.txt LOCALLY' extension from Chrome Web Store"
    Write-Host "  2. Go to youtube.com while logged in"
    Write-Host "  3. Click the extension and export cookies"
    Write-Host "  4. Save the file as cookies.txt in the project root"
}
