# migrate_to_github.ps1
# Run this ONCE from your current project folder (the one inside Google Drive).
# It copies the project to a normal local folder, pushes it to GitHub, and
# leaves Google Drive behind. Afterward, run install_task.ps1 from the NEW
# folder to repoint the 7 AM task.
$ErrorActionPreference = "Stop"
$source = $PSScriptRoot

if (-not (Test-Path -LiteralPath (Join-Path $source "main.py"))) {
    throw "Run this from the project folder - main.py was not found here."
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is not installed. Get it from https://git-scm.com/download/win and re-run."
}

$default = "C:\Users\$env:USERNAME\orhans-morning-book"
$dest = Read-Host "New project location, OUTSIDE Google Drive [Enter for default: $default]"
if ([string]::IsNullOrWhiteSpace($dest)) { $dest = $default }

if (-not (Test-Path -LiteralPath $dest)) {
    New-Item -ItemType Directory -Path $dest | Out-Null
}

# Copy everything except Git internals, generated output, and caches.
$exclude = @(".git", "output", "__pycache__")
Get-ChildItem -LiteralPath $source -Force |
    Where-Object { $exclude -notcontains $_.Name } |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $dest -Recurse -Force }
Write-Host "Copied project to $dest" -ForegroundColor Green

Set-Location -LiteralPath $dest

# Guarantee a .gitignore that keeps secrets and generated files out of Git.
$gitignore = Join-Path $dest ".gitignore"
if (-not (Test-Path -LiteralPath $gitignore)) {
@"
.gmail-smtp.credential.xml
.claude-api.credential.xml
output/
__pycache__/
*.pyc
"@ | Set-Content -LiteralPath $gitignore -Encoding UTF8
}

if (-not (Test-Path -LiteralPath (Join-Path $dest ".git"))) {
    git init -b main | Out-Null
}
git add -A

# SAFETY: never let a credential file be committed.
$leaked = (git status --short) | Select-String -Pattern "credential\.xml"
if ($leaked) {
    throw "STOP: a credential file is staged - do NOT push. Fix .gitignore first."
}
Write-Host "No credential files staged - safe to proceed." -ForegroundColor Green
Write-Host ""
Write-Host "Committing:" -ForegroundColor Cyan
git status --short
if (git status --porcelain) { git commit -m "Orhan's Morning Intelligence" | Out-Null }

$url = "https://github.com/proforhan/orhans-morning-book.git"
git remote remove origin 2>$null
git remote add origin $url

try {
    git push -u origin main
    Write-Host ""
    Write-Host "Pushed to $url" -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "Push was rejected. If you created the repo WITH a README or license," -ForegroundColor Yellow
    Write-Host "the remote has a commit yours does not. Since this repo is brand new" -ForegroundColor Yellow
    Write-Host "it is safe to overwrite it. Run this once:" -ForegroundColor Yellow
    Write-Host "    git push -u origin main --force" -ForegroundColor White
    exit 1
}

Write-Host ""
Write-Host "NEXT STEPS - run these from the NEW folder ($dest):" -ForegroundColor Cyan
Write-Host "  1.  .\install_task.ps1    # repoints the 7 AM task to this folder"
Write-Host "  2.  .\test_delivery.ps1   # send yourself a private test issue"
Write-Host "  3.  Once it looks right, delete the old Google Drive copy."
Write-Host ""
Write-Host "From now on: 'git pull' here updates the project. No more downloading." -ForegroundColor Green
