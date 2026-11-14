# HLK-Web.ps1 - Dev-Toolbox web entry: start the HLK Viewer web server (hlk_web.py).
# Tool runtime.kind stays 'powershell' (CLI = Launch-HLK.ps1), so the Hub launches
# this wrapper instead of resolving Python itself.
# Usage: .\HLK-Web.ps1 [-Port 8780] [-ParentPid <pid>] [-HubOrigin http://127.0.0.1:<p>] [-DataDir <path>]
param(
    [int]$Port = 0,
    [int]$ParentPid = 0,
    [string]$HubOrigin = '',
    [string]$DataDir = ''
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($ParentPid -eq 0) {
    $active = & (Join-Path $here 'Standalone-Update.ps1') -Action Resolve
    if ($active) { & (Join-Path $active 'HLK-Web.ps1') @PSBoundParameters; exit $LASTEXITCODE }
}

$py = & (Join-Path $here 'Standalone-Update.ps1') -Action Python
if (-not $py) {
    # stderr (Hub 只 tail .err 檔); 不用 Write-Error 是因為 ErrorActionPreference=Stop 會跳過 exit 5
    [Console]::Error.WriteLine('找不到相容的 Python。請下載內附 Python 的完整版，或安裝相容的 Python（3.11 以上）。')
    exit 5
}

$argv = @()
if ((Split-Path -Leaf $py) -eq 'py.exe') { $argv += '-3' }
$argv += (Join-Path $here 'hlk_web.py')
if ($Port -gt 0)      { $argv += @('--port', $Port) }
if ($ParentPid -gt 0) { $argv += @('--parent-pid', $ParentPid) }
if ($HubOrigin)       { $argv += @('--hub-origin', $HubOrigin) }
if ($DataDir)         { $argv += @('--data-dir', $DataDir) }

& $py @argv
exit $LASTEXITCODE
