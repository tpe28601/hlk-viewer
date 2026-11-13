param(
    [ValidateSet('Show','Resolve','Open','Check')][string]$Action = 'Show',
    [ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+$')][string]$Version
)

$ErrorActionPreference = 'Stop'
if ($Action -eq 'Open') {
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-STA', '-File', ('"{0}"' -f $PSCommandPath))
    if ($Version) { $arguments += @('-Version', $Version) }
    Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WindowStyle Hidden
    return
}
. (Join-Path $PSScriptRoot 'Tool-Updates.ps1')
$root = $PSScriptRoot
$manifest = [IO.File]::ReadAllText((Join-Path $root 'tool.json')) | ConvertFrom-Json
$data = if ($env:DEVTOOLBOX_DATA) { $env:DEVTOOLBOX_DATA } else { Join-Path $env:LOCALAPPDATA 'DevToolbox' }
$store = Get-ToolUpdateStore $root (Join-Path $data 'standalone')
# A copy launched from the version store must keep following that same store.
$parent = Split-Path $root -Parent
$candidate = Split-Path $parent -Parent
$hubRoot = Split-Path $parent -Parent
if ((Split-Path $parent -Leaf) -eq 'tools' -and
    (Test-Path -LiteralPath (Join-Path $hubRoot 'hub\Tool-Updates.ps1') -PathType Leaf)) {
    $store = Get-ToolUpdateStore $hubRoot (Join-Path $data 'dev-toolbox-hub')
}
if ((Split-Path $parent -Leaf) -eq $manifest.id -and
    (Split-Path $root -Leaf) -eq $manifest.version -and
    (Split-Path $candidate -Leaf) -match '^[A-F0-9]{64}$' -and
    (Split-Path (Split-Path $candidate -Parent) -Leaf) -eq 'tool-updates') {
    $store = $candidate
}
$active = Resolve-ToolUpdateDir $store $manifest.id $manifest.version $root
if ($Action -eq 'Resolve') {
    if ($active -ne $root) { $active }
    return
}

$activeManifest = [IO.File]::ReadAllText((Join-Path $active 'tool.json')) | ConvertFrom-Json
$tool = @{ Id = $manifest.id; Version = $activeManifest.version; Dir = $active }
if ($Action -eq 'Check') {
    $offer = Get-ToolRelease $tool ''
    $update = if ($offer) { @{ version = $offer.version } }
    ConvertTo-Json -InputObject @{ ok = $true; update = $update } -Compress
    return
}

Add-Type -AssemblyName System.Windows.Forms
$title = "$($manifest.name) 更新"
try {
    $offer = Get-ToolRelease $tool ''
    if ($Version -and $offer.version -cne $Version) { throw '可下載的版本已變更，請重新開啟工具以檢查更新。' }
    if (-not $offer) {
        [void][Windows.Forms.MessageBox]::Show("目前版本 v$($tool.Version)，沒有可安裝的新版。", $title)
        return
    }
    $message = "v$($tool.Version) → v$($offer.version)`n`n$($offer.notes)`n`n下載並安裝？下次從原本的啟動檔開啟時會載入新版。"
    if ([Windows.Forms.MessageBox]::Show($message, $title, 'YesNo', 'Question', 'Button2') -ne 'Yes') { return }
    $launcher = @{
        'agents-cfg-manager' = @('Run-Agents-Cfg-Manager.bat', 'Run-Agents-Cfg-Manager-Web.bat')
        'git-ref-manager' = @('Run-Git-Ref-Manager.bat', 'Run-Git-Ref-Manager-Web.bat')
        'build-runner' = @('Run-CLI.bat', 'Run-Web.bat')
        'hlk-viewer' = @('Launch-HLK.ps1', 'HLK-Web.ps1')
        'key-manager' = @('run_windows.bat')
    }
    Install-ToolRelease $store $tool $offer {
        foreach ($file in @('Standalone-Update.ps1', 'Tool-Updates.ps1') + $launcher[$tool.Id]) {
            if (-not (Test-Path -LiteralPath (Join-Path $payload $file) -PathType Leaf)) {
                throw "新版套件缺少 $file，請聯絡發布者。"
            }
        }
    } {} {} | Out-Null
    [void][Windows.Forms.MessageBox]::Show("已安裝 v$($offer.version)。請關閉工具，再用原本的啟動檔開啟。", $title)
} catch {
    [void][Windows.Forms.MessageBox]::Show($_.Exception.Message, $title, 'OK', 'Error')
    exit 1
}
