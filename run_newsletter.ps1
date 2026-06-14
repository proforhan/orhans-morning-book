$ErrorActionPreference = "Stop"
$env:PYTHONDONTWRITEBYTECODE = "1"
Set-Location -LiteralPath $PSScriptRoot
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot "output") | Out-Null
$log = Join-Path $PSScriptRoot "output\scheduler.log"

try {
    Add-Content -LiteralPath $log -Value "[$(Get-Date -Format o)] Orhan's Morning Intelligence run started."

    $gmailFile = Join-Path $PSScriptRoot ".gmail-smtp.credential.xml"
    if (-not (Test-Path -LiteralPath $gmailFile)) {
        throw "Encrypted Gmail credential is missing: $gmailFile (run .\setup_gmail_smtp.ps1)"
    }
    $gmail = Import-Clixml -LiteralPath $gmailFile
    $env:GMAIL_USER = $gmail.UserName
    $env:GMAIL_APP_PASSWORD = $gmail.GetNetworkCredential().Password

    $claudeFile = Join-Path $PSScriptRoot ".claude-api.credential.xml"
    if (Test-Path -LiteralPath $claudeFile) {
        $claude = Import-Clixml -LiteralPath $claudeFile
        $env:ANTHROPIC_API_KEY = $claude.GetNetworkCredential().Password
    } else {
        Add-Content -LiteralPath $log -Value "[$(Get-Date -Format o)] WARNING: Claude API credential missing; falling back to feed summaries."
    }

    python .\main.py *>> $log
    if ($LASTEXITCODE -ne 0) {
        throw "Newsletter process exited with code $LASTEXITCODE."
    }

    Add-Content -LiteralPath $log -Value "[$(Get-Date -Format o)] Run completed successfully."
}
catch {
    Add-Content -LiteralPath $log -Value "[$(Get-Date -Format o)] ERROR: $($_.Exception.Message)"
    throw
}
