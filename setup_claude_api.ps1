$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Orhan's Morning Intelligence - Claude API Setup" -ForegroundColor Cyan
Write-Host "This stores an Anthropic API key encrypted for your Windows account."
Write-Host "Get a key at https://console.anthropic.com (API Keys)."
Write-Host ""

$secureKey = Read-Host "Paste your Anthropic API key (starts with sk-ant-)" -AsSecureString
$credential = [System.Management.Automation.PSCredential]::new("anthropic", $secureKey)

$target = Join-Path $PSScriptRoot ".claude-api.credential.xml"
$credential | Export-Clixml -LiteralPath $target

Write-Host ""
Write-Host "Encrypted Claude API credential saved." -ForegroundColor Green
Write-Host "Run .\test_delivery.ps1 to send a test issue only to orhanerdem@gmail.com."
