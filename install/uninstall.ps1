<#
.SYNOPSIS
    Hermes Updater のスケジュールタスク登録を解除し、任意で実行時データも削除する。

.PARAMETER TaskName
    解除するタスク名 (既定: HermesUpdater-Logon)

.PARAMETER RemoveData
    指定すると $env:LOCALAPPDATA\HermesUpdater (venv/config/state/logs) も削除する。
    既定では削除しない(ログ・設定を残す)。
#>

[CmdletBinding()]
param(
    [string]$TaskName = "HermesUpdater-Logon",
    [switch]$RemoveData
)

$ErrorActionPreference = "Stop"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "==> Stopping and unregistering scheduled task '$TaskName'..."
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
} else {
    Write-Host "==> Task '$TaskName' not found, skipping."
}

# トレイに常駐しているプロセスがあれば、タスク解除だけでは終了しないため案内する
Write-Host "==> If a Hermes Updater tray icon is still running, use its 'Exit' menu item to stop it."

if ($RemoveData) {
    $AppDataDir = Join-Path $env:LOCALAPPDATA "HermesUpdater"
    if (Test-Path $AppDataDir) {
        Write-Host "==> Removing runtime data: $AppDataDir"
        Remove-Item -Recurse -Force -Path $AppDataDir -Confirm:$false
    }
} else {
    Write-Host "==> Runtime data preserved at `$env:LOCALAPPDATA\HermesUpdater` (config/state/logs). Pass -RemoveData to delete."
}

Write-Host "==> Uninstall complete."
