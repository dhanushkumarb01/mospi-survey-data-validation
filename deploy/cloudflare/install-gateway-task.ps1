# Start the hosted read gateway (python -m mospi.gateway serve, 127.0.0.1 only) automatically when you log on.
#   powershell -ExecutionPolicy Bypass -File deploy\cloudflare\install-gateway-task.ps1
# Undo:  powershell -ExecutionPolicy Bypass -File deploy\cloudflare\install-gateway-task.ps1 -Remove
#
# Runs as you (not elevated), restarts on failure, reads its secrets from the repository's git-ignored .env.
# cloudflared itself runs as a Windows service (cloudflared service install), set up separately.
param([switch]$Remove, [string]$Python = "python")
$name = "MoSPI hosted read gateway"
Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
if ($Remove) { Write-Output "Removed: $name"; exit 0 }
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$exe = (Get-Command $Python -ErrorAction Stop).Source
$log = Join-Path $env:LOCALAPPDATA "MoSPI\logs\gateway.log"
$action = New-ScheduledTaskAction -Execute $exe -Argument "-m mospi.gateway serve --log-file `"$log`"" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Description "Signed read-only gateway for the hosted MoSPI workspace (docs/deployment/CLOUDFLARE_TUNNEL.md)" | Out-Null
Start-ScheduledTask -TaskName $name
Write-Output "Registered and started: $name ($exe -m mospi.gateway serve in $repo; log $log)"
