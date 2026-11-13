# Launch-HLK.ps1 - Dev-Toolbox CLI entry for HLK Viewer (tkinter GUI tool).
#   no args      -> open the GUI with a windowed Python (pythonw / pyw), no console window
#   with args    -> run hlk_viewer.pyw CLI mode in this console, args passed through:
#                   --cli-export-all <hlkx> <outdir>        export result HTML reports
#                   --cli-export-all-logs <hlkx> <outdir>   export HTML reports with full logs
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ToolArgs)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $root 'hlk_viewer.pyw'

function Resolve-HlkPython([bool]$Gui) {
    # Same order as hub.ps1 Resolve-HubPython: DEVTOOLBOX_PYTHON > tool .venv > py/pyw launcher > PATH python (skip WindowsApps stubs)
    $exeName = if ($Gui) { 'pythonw.exe' } else { 'python.exe' }
    if ($env:DEVTOOLBOX_PYTHON -and (Test-Path -LiteralPath $env:DEVTOOLBOX_PYTHON)) {
        if ($Gui) {
            $sibling = Join-Path (Split-Path -Parent $env:DEVTOOLBOX_PYTHON) 'pythonw.exe'
            if (Test-Path -LiteralPath $sibling) { return $sibling }
        }
        return $env:DEVTOOLBOX_PYTHON
    }
    $venv = Join-Path $root ".venv\Scripts\$exeName"
    if (Test-Path -LiteralPath $venv) { return $venv }
    $launcher = if ($Gui) { 'pyw' } else { 'py' }
    foreach ($l in @(Get-Command $launcher -ErrorAction SilentlyContinue)) {
        if ($l.Source -notmatch 'WindowsApps') { return $l.Source }
    }
    foreach ($c in @(Get-Command $exeName -ErrorAction SilentlyContinue)) {
        if ($c.Source -notmatch 'WindowsApps') { return $c.Source }
    }
    return $null
}

if (-not $ToolArgs -or $ToolArgs.Count -eq 0) {
    $guiPy = Resolve-HlkPython $true
    if (-not $guiPy) { Write-Error '找不到 Python（安裝 py 啟動器、在工具資料夾建 .venv 或設 DEVTOOLBOX_PYTHON）'; exit 2 }
    Start-Process -FilePath $guiPy -ArgumentList "`"$script`"" -WorkingDirectory $root
    exit 0
}

# CLI mode: hlk_viewer.pyw expects "<flag> <hlkx> <outdir>"; check before Python so
# a missing path prints usage here instead of a Python IndexError traceback.
if ($ToolArgs[0] -in '--cli-export-all', '--cli-export-all-logs' -and $ToolArgs.Count -lt 3) {
    Write-Error "用法：Launch-HLK.ps1 $($ToolArgs[0]) <hlkx> <outdir>（雨個參數都必填）"
    exit 2
}

$conPy = Resolve-HlkPython $false
if (-not $conPy) { Write-Error '找不到 Python（安裝 py 啟動器、在工具資料夾建 .venv 或設 DEVTOOLBOX_PYTHON）'; exit 2 }
& $conPy $script @ToolArgs
exit $LASTEXITCODE
