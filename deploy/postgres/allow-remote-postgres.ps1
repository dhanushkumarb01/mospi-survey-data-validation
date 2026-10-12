# Allow inbound TCP 5432 to PostgreSQL for the hosted (Vercel) reader.  Run in an elevated PowerShell.
#   powershell -ExecutionPolicy Bypass -File deploy\postgres\allow-remote-postgres.ps1
# Undo:  powershell -ExecutionPolicy Bypass -File deploy\postgres\allow-remote-postgres.ps1 -Remove
#
# Only run this once the router actually forwards a public port to this computer (docs/deployment/POSTGRESQL.md).
# PostgreSQL itself already admits only mospi_reader, only over TLS, and rejects every other remote login.
#
# SUPERSEDED (12 Oct 2026): the hosted instance now reaches PostgreSQL through the Cloudflare Tunnel read gateway
# (docs/deployment/CLOUDFLARE_TUNNEL.md); PostgreSQL must NOT accept connections from beyond this computer.
# Adding the rule is refused unless -DirectExposure is given; -Remove still works.
param([switch]$Remove, [switch]$DirectExposure)
$name = "MoSPI PostgreSQL hosted reader (TCP 5432)"
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Run this script in an elevated (Administrator) PowerShell."; exit 1
}
Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if ($Remove) { Write-Output "Removed: $name"; exit 0 }
if (-not $DirectExposure) { Write-Error "Superseded by the Cloudflare Tunnel gateway; nothing was opened. See docs/deployment/CLOUDFLARE_TUNNEL.md."; exit 1 }
# The service runs pg_ctl.exe; the process that listens on 5432 is postgres.exe in the same folder.
$ctl = (Get-CimInstance Win32_Service -Filter "Name LIKE 'postgresql%'" | Select-Object -First 1).PathName -replace '^"([^"]+)".*$', '$1'
$exe = Join-Path (Split-Path $ctl) "postgres.exe"
New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5432 -Program $exe -Profile Any | Out-Null
Write-Output "Added: $name for $exe"
