# cli-kit 1.0.0 — Dev-Toolbox 共用 CLI 樣式（PowerShell 5.1 / 7+）
# 正本在 Dev-Toolbox/ui-kit，請勿直接修改工具內的複本。
# 用法：. (Join-Path $PSScriptRoot 'cli-kit.ps1')
# 顏色意義：綠＝成功、黃＝警告、紅＝錯誤、灰＝dry-run／次要資訊、青＝標題。

$script:TbNoColor = [bool]$env:NO_COLOR

function Set-TbNoColor([bool]$Value) { $script:TbNoColor = $Value }

function Write-TbLine([string]$Text, [string]$Color) {
    if ($script:TbNoColor -or -not $Color) { Write-Host $Text }
    else { Write-Host $Text -ForegroundColor $Color }
}

function Write-TbTitle([string]$Title, [string]$Subtitle) {
    $bar = '=' * 48
    Write-TbLine $bar 'Cyan'
    Write-TbLine ("  " + $Title) 'Cyan'
    if ($Subtitle) { Write-TbLine ("  " + $Subtitle) 'DarkGray' }
    Write-TbLine $bar 'Cyan'
}

function Write-TbSection([string]$Text) { Write-TbLine ("`n=== $Text ===") 'Yellow' }
function Write-TbOk([string]$Text)      { Write-TbLine ("[OK] $Text") 'Green' }
function Write-TbWarn([string]$Text)    { Write-TbLine ("[!]  $Text") 'Yellow' }
function Write-TbErr([string]$Text)     { Write-TbLine ("[X]  $Text") 'Red' }
function Write-TbDry([string]$Text)     { Write-TbLine ("[dry-run] $Text") 'DarkGray' }
function Write-TbInfo([string]$Text)    { Write-TbLine $Text 'Gray' }

function Read-TbConfirm([string]$Question, [switch]$AssumeYes) {
    # 一般確認：預設「否」。
    if ($AssumeYes) { return $true }
    $answer = Read-Host "$Question [y/N]"
    return ($answer -match '^(?i:y|yes)$')
}

function Read-TbConfirmName([string]$Question, [string]$Expected, [switch]$AssumeYes) {
    # 不可逆動作：必須輸入目標名稱才執行（--yes 可略過，供排程使用）。
    if ($AssumeYes) { return $true }
    Write-TbWarn $Question
    $answer = Read-Host "請輸入「$Expected」確認，其他輸入代表取消"
    return ($answer -ceq $Expected)
}

function Show-TbMenu([string]$Title, [object[]]$Items) {
    # $Items：@(@{ Key='1'; Label='...' }, ...)；回傳使用者輸入的 Key（不在清單內則回傳 $null）。
    if ($Title) { Write-TbSection $Title }
    foreach ($it in $Items) { Write-Host ("[{0}] {1}" -f $it.Key, $it.Label) }
    $keys = @($Items | ForEach-Object { [string]$_.Key })
    $choice = Read-Host ("`n請選擇 [{0}]" -f ($keys -join '/'))
    if ($keys -contains $choice) { return $choice }
    return $null
}

# Exit code（見 TOOL-SPEC.md 第 4 節）
$script:TbExit = @{ Ok = 0; Failed = 1; Partial = 2; BadArgs = 3; Cancelled = 4; Env = 5 }
