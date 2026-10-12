# Kyeon - one-line install. No Python needed. Paste this into PowerShell:
#
#   irm https://raw.githubusercontent.com/kcc920926-droid/kyeon/main/install.ps1 | iex
#
# What it does (no admin rights, nothing outside your user profile):
#   1. reads latest.json from this repository
#   2. downloads kyeon.exe from the GitHub release and checks its SHA-256 against latest.json
#   3. runs "kyeon.exe --setup --yes": copies it to %LOCALAPPDATA%\Programs\Kyeon, runs it at logon,
#      adds an entry to Settings > Apps (that is where you remove it), and starts it
# Read the script before you run it; it is short.
#
# For testing only: KYEON_SOURCE = latest.json URL or a folder that holds latest.json and the exe.

function Install-Kyeon {
    $ErrorActionPreference = 'Stop'
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch { }

    $source = $env:KYEON_SOURCE
    if (-not $source) { $source = 'https://raw.githubusercontent.com/kcc920926-droid/kyeon/main/latest.json' }
    $isUrl = $source -match '^https?://'

    # 1. latest.json
    if ($isUrl) {
        $json = [Text.Encoding]::UTF8.GetString((Invoke-WebRequest -Uri $source -UseBasicParsing).RawContentStream.ToArray())
        $folder = $null
    } else {
        $manifestPath = if (Test-Path -LiteralPath $source -PathType Container) { Join-Path $source 'latest.json' } else { $source }
        $json = [IO.File]::ReadAllText($manifestPath, [Text.Encoding]::UTF8)
        $folder = Split-Path -Parent $manifestPath
    }
    $m = $json | ConvertFrom-Json
    if ($m.app -ne 'kyeon' -or $m.schema -ne 1) { throw 'latest.json is not a Kyeon manifest' }
    $rt = $m.runtime
    if (-not $rt -or ([string]$rt.sha256) -notmatch '^[0-9a-f]{64}$') { throw 'latest.json has no valid kyeon.exe entry' }

    # 2. kyeon.exe, checked against its hash before it is run
    $work = Join-Path ([IO.Path]::GetTempPath()) ('kyeon-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $work | Out-Null
    $exe = Join-Path $work 'kyeon.exe'
    try {
        if ($isUrl) {
            $url = [string]$rt.url
            if (-not $url.StartsWith('https://github.com/')) { throw 'kyeon.exe points to an unexpected server' }
            Invoke-WebRequest -Uri $url -OutFile $exe -UseBasicParsing
        } else {
            $local = [string]$rt.url
            if (-not [IO.Path]::IsPathRooted($local)) { $local = Join-Path $folder $local }
            Copy-Item -LiteralPath $local -Destination $exe -Force
        }
        $got = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLower()
        if ($got -ne [string]$rt.sha256) { throw 'kyeon.exe does not match the hash in latest.json; nothing was installed' }

        # 3. let kyeon.exe install itself (WaitForExit on this process only; the widget it starts keeps running)
        $p = Start-Process -FilePath $exe -ArgumentList '--setup', '--yes' -PassThru
        $p.WaitForExit()
        if ($p.ExitCode -ne 0) { throw "setup failed (exit code $($p.ExitCode))" }
        Write-Host '[Kyeon] Installed. It starts at every logon; to remove it use Settings > Apps > Kyeon.' -ForegroundColor Green
    } finally {
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }
}

try { Install-Kyeon } catch { Write-Host "[Kyeon] $($_.Exception.Message)" -ForegroundColor Red }
