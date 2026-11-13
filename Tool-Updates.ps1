# Release sources are explicit so local and private tools stay outside the public update channel.
$script:ToolReleaseRepos = @{
    'agents-cfg-manager' = 'tpe28601/cfg-manager'
    'build-runner' = 'tpe28601/build-runner'
    'git-ref-manager' = 'tpe28601/git-ref-manager'
    'key-manager' = 'tpe28601/key-manager'
    'hlk-viewer' = 'tpe28601/hlk-viewer'
    'dev-toolbox' = 'tpe28601/Dev-Toolbox'
}
$script:MaxToolZipBytes = 100MB

function Get-ToolUpdateStore([string]$Root, [string]$DataRoot) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes([IO.Path]::GetFullPath($Root).ToUpperInvariant())
        $key = [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '')
        return (Join-Path $DataRoot "tool-updates\$key")
    } finally { $sha.Dispose() }
}

function ConvertTo-ToolVersion([string]$Text) {
    if ($Text -match '^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$') {
        $version = $null
        if ([version]::TryParse($Text, [ref]$version)) { return $version }
    }
}

function Read-ActiveToolVersion([string]$ToolStore) {
    $pointer = Join-Path $ToolStore 'active.txt'
    if (Test-Path -LiteralPath $pointer -PathType Leaf) {
        return [IO.File]::ReadAllText($pointer).Trim()
    }
}

function Resolve-ToolUpdateDir([string]$Store, [string]$Id, [string]$BundledVersion, [string]$BundledDir) {
    if ($script:ToolReleaseRepos.ContainsKey($Id)) {
        try {
            $toolStore = Join-Path $Store $Id
            $active = Read-ActiveToolVersion $toolStore
            $version = ConvertTo-ToolVersion $active
            $bundled = ConvertTo-ToolVersion $BundledVersion
            if ($version -and $bundled -and $version -gt $bundled) {
                $dir = Join-Path $toolStore $active
                $m = [IO.File]::ReadAllText((Join-Path $dir 'tool.json')) | ConvertFrom-Json
                if ($m.id -ceq $Id -and $m.version -ceq $active) { return $dir }
            }
        } catch { }
    }
    return $BundledDir
}

function Select-ToolRelease($Tool, [string]$Repo, [string]$HubVersion, $Releases) {
    $current = ConvertTo-ToolVersion $Tool.Version
    $hub = ConvertTo-ToolVersion $HubVersion
    if (-not $current -or ($HubVersion -and -not $hub)) { throw '工具和 Hub 必須使用正式版號（X.Y.Z）才能檢查更新。' }

    $best = $null
    $bestVersion = $current
    foreach ($release in $Releases) {
        if ($release.draft -or $release.prerelease -or $release.tag_name -cnotmatch '^v(.+)$') { continue }
        $text = $Matches[1]
        $version = ConvertTo-ToolVersion $text
        if (-not $version -or $version -le $bestVersion) { continue }
        $name = "$($Tool.Id)-$text.zip"
        $assets = @($release.assets | Where-Object { $_.name -ceq $name -and $_.state -eq 'uploaded' })
        if ($assets.Count -ne 1) { continue }
        $asset = $assets[0]
        if ($Tool.Id -ne 'dev-toolbox') {
            if ($asset.label -cnotmatch '^min-hub=(.+)$') { continue }
            $minHub = ConvertTo-ToolVersion $Matches[1]
            if (-not $minHub -or ($hub -and $minHub -gt $hub)) { continue }
        }
        if ($asset.digest -notmatch '^sha256:([0-9a-f]{64})$') { continue }
        $hash = $Matches[1]
        $size = [long]$asset.size
        if ($size -le 0 -or $size -gt $script:MaxToolZipBytes) { continue }
        $notes = [string]$release.body
        $best = [pscustomobject]@{
            version = $text
            url = "https://github.com/$Repo/releases/download/v$text/$name"
            sha256 = $hash
            size = $size
            notes = $notes.Substring(0, [Math]::Min($notes.Length, 2000))
        }
        $bestVersion = $version
    }
    return $best
}

function Get-ToolRelease($Tool, [string]$HubVersion) {
    $repo = $script:ToolReleaseRepos[$Tool.Id]
    if (-not $repo) { throw '這個工具沒有設定公開更新來源。' }
    # Windows PowerShell 5.1 can default to older TLS protocols.
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $headers = @{ Accept = 'application/vnd.github+json'; 'X-GitHub-Api-Version' = '2022-11-28' }
    $releases = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/releases?per_page=100" -Headers $headers -TimeoutSec 12
    return (Select-ToolRelease $Tool $repo $HubVersion $releases)
}

function Get-ToolReleaseFile($Offer, [string]$Path) {
    Add-Type -AssemblyName System.Net.Http
    $client = [Net.Http.HttpClient]::new()
    $timeout = [Threading.CancellationTokenSource]::new(120000)
    try {
        $response = $client.GetAsync($Offer.url, [Net.Http.HttpCompletionOption]::ResponseHeadersRead, $timeout.Token).GetAwaiter().GetResult()
        try {
            [void]$response.EnsureSuccessStatusCode()
            if ($response.RequestMessage.RequestUri.Scheme -ne 'https') { throw '下載來源必須使用 HTTPS。' }
            $inputStream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
            $outputStream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew)
            try {
                $buffer = [byte[]]::new(65536)
                $total = 0L
                while (($count = $inputStream.ReadAsync($buffer, 0, $buffer.Length, $timeout.Token).GetAwaiter().GetResult()) -gt 0) {
                    $total += $count
                    if ($total -gt $Offer.size) { throw '下載檔案大小與 Release 不符。' }
                    $outputStream.Write($buffer, 0, $count)
                }
            } finally { $outputStream.Dispose() }
        } finally { $response.Dispose() }
    } finally { $timeout.Dispose(); $client.Dispose() }
}

function Resolve-ToolPackagePath([string]$Root, [string]$RelativePath) {
    $relative = $RelativePath.Replace('\', '/').TrimEnd('/')
    foreach ($part in $relative.Split('/')) {
        if (-not $part -or $part -match '[<>:"|?*\x00-\x1f]|[. ]$|^\.(?:git|venv)$|^(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)') {
            throw "更新套件包含無效路徑：$RelativePath"
        }
    }
    return (Join-Path $Root $relative)
}

function Expand-ToolRelease([string]$Zip, [string]$Destination, [string]$Id, [string]$Version) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [void][IO.Directory]::CreateDirectory($Destination)
    $archive = [IO.Compression.ZipFile]::OpenRead($Zip)
    try {
        $total = 0L
        if ($archive.Entries.Count -gt 10000) { throw '更新套件包含過多檔案。' }
        foreach ($entry in $archive.Entries) {
            $path = Resolve-ToolPackagePath $Destination $entry.FullName
            if (($entry.ExternalAttributes -shr 16 -band 0xF000) -eq 0xA000) { throw '更新套件包含符號連結。' }
            $total += $entry.Length
            if ($total -gt 500MB) { throw '更新套件解壓後超過 500 MB。' }
            if ($entry.FullName -match '[/\\]$') {
                [void][IO.Directory]::CreateDirectory($path)
                continue
            }
            [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path))
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $path)
        }
    } finally { $archive.Dispose() }

    $m = [IO.File]::ReadAllText((Join-Path $Destination 'tool.json')) | ConvertFrom-Json
    $kind = if ($Id -eq 'dev-toolbox') { 'hub' } else { 'tool' }
    if ($m.id -cne $Id -or $m.version -cne $Version -or $m.kind -cne $kind -or $m.specVersion -ne 1 -or
        $m.runtime.kind -notin @('powershell', 'python', 'exe') -or -not ($m.web -or $m.cli)) {
        throw '更新套件的 tool.json 與工具或版本不符。'
    }
    foreach ($mode in @($m.web, $m.cli)) {
        if (-not $mode) { continue }
        $entryPath = Resolve-ToolPackagePath $Destination ([string]$mode.entry)
        if (-not (Test-Path -LiteralPath $entryPath -PathType Leaf)) { throw "更新套件缺少入口：$($mode.entry)" }
    }
    if ($kind -eq 'hub') {
        foreach ($file in @('hub/Hub-Web.ps1', 'hub/hub.ps1', 'hub/Tool-Updates.ps1', 'hub/ui/index.html', 'hub/ui/app.js', 'ui-kit/cli-kit.ps1', 'ui-kit/ui-kit.css')) {
            if (-not (Test-Path -LiteralPath (Join-Path $Destination $file) -PathType Leaf)) { throw "Hub 套件缺少 $file" }
        }
    }
}

function Write-ActiveToolVersion([string]$ToolStore, [string]$Version, [string]$Stage) {
    $pointer = Join-Path $ToolStore 'active.txt'
    if (-not $Version) { [IO.File]::Delete($pointer); return }
    $pending = Join-Path $Stage 'active.txt'
    [IO.File]::WriteAllText($pending, $Version)
    if ([IO.File]::Exists($pointer)) {
        [IO.File]::Replace($pending, $pointer, (Join-Path $Stage 'previous-active.txt'))
    } else { [IO.File]::Move($pending, $pointer) }
}

function Install-ToolRelease([string]$Store, $Tool, $Offer, [scriptblock]$BeforeSwitch, [scriptblock]$AfterSwitch, [scriptblock]$Recover) {
    $version = ConvertTo-ToolVersion $Offer.version
    if (-not $script:ToolReleaseRepos.ContainsKey($Tool.Id) -or -not $version -or $version -le (ConvertTo-ToolVersion $Tool.Version)) {
        throw '找不到可安裝的新版。'
    }
    $toolStore = Join-Path $Store $Tool.Id
    [void][IO.Directory]::CreateDirectory($toolStore)
    $lock = [IO.File]::Open((Join-Path $toolStore 'update.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $stage = Join-Path $toolStore ([guid]::NewGuid().ToString('N'))
    try {
        $previous = Read-ActiveToolVersion $toolStore
        if ($previous -and (ConvertTo-ToolVersion $previous) -ge $version) { throw '這個工具已更新，請重新檢查版本。' }
        [void][IO.Directory]::CreateDirectory($stage)
        $zip = Join-Path $stage 'release.zip'
        $payload = Join-Path $stage 'payload'
        Get-ToolReleaseFile $Offer $zip
        if ((Get-Item -LiteralPath $zip).Length -ne $Offer.size -or (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ne $Offer.sha256) {
            throw '下載檔案大小或 SHA-256 與 Release 不符。'
        }
        Expand-ToolRelease $zip $payload $Tool.Id $Offer.version

        $destination = Join-Path $toolStore $Offer.version
        $switched = $false
        $moved = $false
        try {
            & $BeforeSwitch
            # A previous interrupted update may have prepared this version without activating it.
            if ([IO.Directory]::Exists($destination)) {
                [IO.Directory]::Move($destination, (Join-Path $stage 'stale'))
            }
            [IO.Directory]::Move($payload, $destination)
            $moved = $true
            Write-ActiveToolVersion $toolStore $Offer.version $stage
            $switched = $true
            & $AfterSwitch
        } catch {
            $failure = $_
            if ($switched) { Write-ActiveToolVersion $toolStore $previous $stage }
            if ($moved) {
                try { [IO.Directory]::Move($destination, (Join-Path $stage 'failed')) } catch { }
            }
            try { & $Recover } catch {
                throw "$($failure.Exception.Message) 舊版已保留，但重新啟動失敗：$($_.Exception.Message)"
            }
            throw $failure
        }
        return [pscustomobject]@{ version = $Offer.version }
    } finally {
        try {
            if ([IO.Directory]::Exists($stage)) { [IO.Directory]::Delete($stage, $true) }
        } catch { }
        $lock.Dispose()
    }
}
