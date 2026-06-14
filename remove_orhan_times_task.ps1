# Removes the OLD "Orhan Times" scheduled task so you do not receive two newsletters.
# Run this only after you have verified Orhan's Morning Intelligence is delivering correctly.
$ErrorActionPreference = "Stop"
$oldTask = "Orhan Times Daily Newsletter"
if (Get-ScheduledTask -TaskName $oldTask -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $oldTask -Confirm:$false
    Write-Host "Removed scheduled task: $oldTask" -ForegroundColor Green
    Write-Host "You can now delete the 'Orhan Times' folder whenever you like."
} else {
    Write-Host "Task '$oldTask' was not found - nothing to remove." -ForegroundColor Yellow
}
