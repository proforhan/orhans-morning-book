$ErrorActionPreference = "Stop"
$env:PYTHONDONTWRITEBYTECODE = "1"
Set-Location -LiteralPath $PSScriptRoot

$gmailFile = Join-Path $PSScriptRoot ".gmail-smtp.credential.xml"
if (-not (Test-Path -LiteralPath $gmailFile)) {
    throw "Run .\setup_gmail_smtp.ps1 first."
}
$gmail = Import-Clixml -LiteralPath $gmailFile
$env:GMAIL_USER = $gmail.UserName
$env:GMAIL_APP_PASSWORD = $gmail.GetNetworkCredential().Password

$claudeFile = Join-Path $PSScriptRoot ".claude-api.credential.xml"
if (Test-Path -LiteralPath $claudeFile) {
    $claude = Import-Clixml -LiteralPath $claudeFile
    $env:ANTHROPIC_API_KEY = $claude.GetNetworkCredential().Password
} else {
    Write-Host "NOTE: Claude API credential missing; the test will use plain feed summaries." -ForegroundColor Yellow
}

# Private test: send only to Orhan, do not consume the chart-of-the-day state.
$env:OMI_RECIPIENTS = "orhanerdem@gmail.com"
$env:OMI_PRESERVE_CHART_STATE = "true"

python .\main.py
