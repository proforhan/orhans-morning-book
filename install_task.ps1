param(
    [string]$TaskName = "Orhan's Morning Intelligence Daily Newsletter"
)

$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "run_newsletter.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Daily -At "7:00 AM"
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Generate and email Orhan's Morning Intelligence at 7:00 AM Central." -Force
Get-ScheduledTask -TaskName $TaskName | Format-List TaskName,State,Actions,Triggers,Principal,Settings
