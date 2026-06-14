$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Orhan's Morning Intelligence - Gmail SMTP Setup" -ForegroundColor Cyan
Write-Host "This stores a Google app password encrypted for your Windows account."
Write-Host "It does not store your normal Gmail password."
Write-Host ""

Write-Host "Gmail account: orhanerdem@gmail.com"
$securePassword = Read-Host "Enter the 16-character Google app password" -AsSecureString
$credential = [System.Management.Automation.PSCredential]::new(
    "orhanerdem@gmail.com",
    $securePassword
)

$target = Join-Path $PSScriptRoot ".gmail-smtp.credential.xml"
$credential | Export-Clixml -LiteralPath $target

Write-Host ""
Write-Host "Encrypted Gmail credential saved." -ForegroundColor Green
Write-Host "Run .\test_delivery.ps1 to send a test issue only to orhanerdem@gmail.com."
