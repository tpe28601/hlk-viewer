# Launch-HLK.ps1 - Dev-Toolbox CLI entry for HLK Viewer (tkinter GUI tool).
#   no args      -> open the GUI with a windowed Python (pythonw / pyw), no console window
#   with args    -> run hlk_viewer.pyw CLI mode in this console, args passed through:
#                   --cli-export-all <hlkx> <outdir>        export result HTML reports
#                   --cli-export-all-logs <hlkx> <outdir>   export HTML reports with full logs
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ToolArgs)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$active = & (Join-Path $root 'Standalone-Update.ps1') -Action Resolve
if ($active) { & (Join-Path $active 'Launch-HLK.ps1') @ToolArgs; exit $LASTEXITCODE }
$script = Join-Path $root 'hlk_viewer.pyw'

function Resolve-HlkPython([bool]$Gui) {
    $python = & (Join-Path $root 'Standalone-Update.ps1') -Action Python
    if ($python -and $Gui) {
        $windowed = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
        if (Test-Path -LiteralPath $windowed -PathType Leaf) { return $windowed }
    }
    return $python
}

if (-not $ToolArgs -or $ToolArgs.Count -eq 0) {
    $guiPy = Resolve-HlkPython $true
    if (-not $guiPy) { [Console]::Error.WriteLine('找不到相容的 Python（需要 Python 3.11 和 Tkinter）。請下載完整版，或安裝相容的 Python。'); exit 2 }
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
if (-not $conPy) { [Console]::Error.WriteLine('找不到相容的 Python（需要 Python 3.11 和 Tkinter）。請下載完整版，或安裝相容的 Python。'); exit 2 }
& $conPy $script @ToolArgs
exit $LASTEXITCODE
