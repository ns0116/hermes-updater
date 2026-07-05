<#
.SYNOPSIS
    Hermes Updater を専用venvにインストールし、ログオン時起動のタスクスケジューラに登録する。

.DESCRIPTION
    実装計画書 2節(ランタイム分離の方針)・8節(自動起動)に対応。
    - 実行環境: $env:LOCALAPPDATA\HermesUpdater\venv (hermes-agentのvenvとは完全に独立)
    - タスク: ログオン時トリガー、対話的ログオンの現在のユーザーとして実行(トレイアイコン表示のため)
    - 実行コマンド: <venv>\Scripts\pythonw.exe -m hermes_updater (コンソールウィンドウなし)

    このスクリプトはタスクスケジューラへの登録を行うため、CLAUDE.mdのガードレールに従い
    ユーザーの明示的な確認を得てから実行すること(SEMI_AUTO)。

.PARAMETER SourceDir
    hermes-updaterのソースディレクトリ (既定: このスクリプトの2階層上)

.PARAMETER TaskName
    登録するタスク名 (既定: HermesUpdater-Logon)
#>

[CmdletBinding()]
param(
    [string]$SourceDir = (Resolve-Path (Join-Path $PSScriptRoot "..")),
    [string]$TaskName = "HermesUpdater-Logon"
)

$ErrorActionPreference = "Stop"

$AppDataDir = Join-Path $env:LOCALAPPDATA "HermesUpdater"
$VenvDir = Join-Path $AppDataDir "venv"
$PythonwExe = Join-Path $VenvDir "Scripts\pythonw.exe"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"

Write-Host "==> Hermes Updater installer"
Write-Host "    Source: $SourceDir"
Write-Host "    Runtime: $VenvDir"

# --- 1. 専用venvの作成 (hermes-agentのvenvには一切触れない) ---
if (-not (Test-Path $PythonExe)) {
    Write-Host "==> Creating dedicated venv via uv..."
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) {
        throw "uv command not found on PATH. Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
    }
    New-Item -ItemType Directory -Force -Path $AppDataDir | Out-Null
    & uv venv $VenvDir --python 3.13
    if ($LASTEXITCODE -ne 0) { throw "uv venv failed with exit code $LASTEXITCODE" }
} else {
    Write-Host "==> Venv already exists, reusing: $VenvDir"
}

# --- 2. hermes-updater本体のインストール(専用venvのみ、hermes-agentのvenvには触れない) ---
Write-Host "==> Installing hermes-updater into dedicated venv..."
& uv pip install --python $PythonExe --editable $SourceDir
if ($LASTEXITCODE -ne 0) { throw "uv pip install failed with exit code $LASTEXITCODE" }

if (-not (Test-Path $PythonwExe)) {
    throw "pythonw.exe not found after venv creation: $PythonwExe"
}

# --- 2.5. pythonw.exeがGUIサブシステムかどうかを検証し、必要なら修復する ---
# uv(0.11.26時点)が生成する venv\Scripts\pythonw.exe は、venv\Scripts\python.exe と同一の
# コンソールサブシステム版バイナリになる既知の不具合がある(実機で再現確認済み)。放置すると
# ログオン起動時にWindows 11既定のWindows Terminalがコンソールウィンドウを表示し続ける
# (Issue #1)。venv自身のpython.exe(起動スタブとして動作確認済み)を複製し、PEヘッダの
# SubsystemフィールドのみをGUI(2)に書き換えて修復する。
#
# 注意: ベースインストール側(pyvenv.cfgの`home`が指す先)の本物のpythonw.exeをそのまま
# 持ってきてはいけない。あちらは隣接するpython3xx.dllに依存するバイナリのため、
# venv\Scripts直下に置くとSTATUS_DLL_NOT_FOUND(0xC0000135)で起動不能になる
# (過去にこれで実際に起動不能を起こした実績がある)。
function Test-IsGuiSubsystemExe([string]$ExePath) {
    $bytes = [System.IO.File]::ReadAllBytes($ExePath)
    $peOffset = [BitConverter]::ToInt32($bytes, 0x3C)
    $subsystem = [BitConverter]::ToUInt16($bytes, $peOffset + 4 + 20 + 68)
    return $subsystem -eq 2
}

if (-not (Test-IsGuiSubsystemExe $PythonwExe)) {
    Write-Host "==> pythonw.exe is not a GUI-subsystem executable (known uv venv issue). Repairing..."
    $bytes = [System.IO.File]::ReadAllBytes($PythonExe)
    $peOffset = [BitConverter]::ToInt32($bytes, 0x3C)
    $subsystemOffset = $peOffset + 4 + 20 + 68
    $bytes[$subsystemOffset] = 2
    [System.IO.File]::WriteAllBytes($PythonwExe, $bytes)
    if (-not (Test-IsGuiSubsystemExe $PythonwExe)) {
        throw "Failed to repair pythonw.exe: still not GUI-subsystem after patch"
    }
    Write-Host "    Repaired: derived GUI-subsystem pythonw.exe from python.exe"
}

# --- 3. ログオントリガーのタスクスケジューラ登録 ---
Write-Host "==> Registering scheduled task '$TaskName' (AtLogOn, interactive user)..."

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "    Existing task found, unregistering first..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction -Execute $PythonwExe -Argument "-m hermes_updater"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null

Write-Host "==> Done. Task '$TaskName' will start hermes-updater at next logon."
Write-Host "    To start it immediately: Start-ScheduledTask -TaskName '$TaskName'"
