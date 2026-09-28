[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $env:USERPROFILE 'Fulton Offsite Backups'),
    [string]$Server = 'ste@192.168.0.15',
    [string]$IdentityFile = (Join-Path $env:USERPROFILE '.ssh\codex_fultons_ed25519')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Repository = Split-Path -Parent $PSScriptRoot
$BackupManager = Join-Path $PSScriptRoot 'backup_manager.py'
$SevenZip = 'C:\Program Files (x86)\Universal Extractor\bin\7z.exe'
$RemoteRoot = '/disk2/backups/fultons-quiz'
$TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$Work = Join-Path $TempRoot ('fultons-offhost-' + [Guid]::NewGuid().ToString('N'))
$Restore = Join-Path $TempRoot ('fultons-offhost-restore-' + [Guid]::NewGuid().ToString('N'))

function Assert-NativeSuccess([string]$Operation) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed with exit code $LASTEXITCODE"
    }
}

function Remove-TaskTemporaryDirectory([string]$Path, [string]$Prefix) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $Resolved = [IO.Path]::GetFullPath($Path)
    $Leaf = Split-Path $Resolved -Leaf
    if (-not $Resolved.StartsWith($TempRoot, [StringComparison]::OrdinalIgnoreCase) -or
        -not $Leaf.StartsWith($Prefix, [StringComparison]::Ordinal)) {
        throw "Refusing to remove unsafe temporary path: $Resolved"
    }
    Remove-Item -LiteralPath $Resolved -Recurse -Force
}

if (-not (Test-Path -LiteralPath $IdentityFile -PathType Leaf)) {
    throw "SSH identity file is unavailable: $IdentityFile"
}
if (-not (Test-Path -LiteralPath $BackupManager -PathType Leaf)) {
    throw "Backup verifier is unavailable: $BackupManager"
}
if (-not (Test-Path -LiteralPath $SevenZip -PathType Leaf)) {
    throw "7-Zip is unavailable: $SevenZip"
}

New-Item -ItemType Directory -Path $Destination -Force | Out-Null
New-Item -ItemType Directory -Path $Work, $Restore | Out-Null

try {
    $FindCommand = "find $RemoteRoot -maxdepth 1 -mindepth 1 -type d -name 'fultons-quiz-*' -printf '%f\n' | sort | tail -n 1"
    $BackupName = (& ssh -i $IdentityFile -p 22 -o BatchMode=yes $Server $FindCommand).Trim()
    Assert-NativeSuccess 'Latest-backup lookup'
    if ($BackupName -notmatch '^fultons-quiz-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$') {
        throw "Unexpected backup name: $BackupName"
    }

    $Existing = Get-ChildItem -LiteralPath $Destination -Filter '*.json' -File |
        ForEach-Object {
            try { Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json } catch { $null }
        } |
        Where-Object { $_.source_backup -eq $BackupName } |
        Select-Object -First 1
    if ($null -ne $Existing) {
        Write-Output "Off-host copy already exists for $BackupName"
        exit 0
    }

    $RemotePath = "$RemoteRoot/$BackupName"
    & scp -i $IdentityFile -P 22 -r ($Server + ':' + $RemotePath) $Work
    Assert-NativeSuccess 'Secure copy'

    $Downloaded = Join-Path $Work $BackupName
    & python $BackupManager verify $Downloaded
    Assert-NativeSuccess 'Downloaded-backup verification'

    $Password = [Convert]::ToHexString(
        [Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
    ).ToLowerInvariant()
    $Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
    $Base = "fultons-offhost-$Stamp-$BackupName"
    $StagedArchive = Join-Path $Work ($Base + '.7z')

    Push-Location $Work
    try {
        & $SevenZip a -t7z -mx=0 -mhe=on ('-p' + $Password) $StagedArchive $BackupName
        Assert-NativeSuccess 'Encrypted archive creation'
    }
    finally {
        Pop-Location
    }

    & $SevenZip t ('-p' + $Password) $StagedArchive
    Assert-NativeSuccess 'Encrypted archive test'
    & $SevenZip x -y ('-p' + $Password) ('-o' + $Restore) $StagedArchive
    Assert-NativeSuccess 'Clean restore extraction'
    & python $BackupManager verify (Join-Path $Restore $BackupName)
    Assert-NativeSuccess 'Clean restore verification'

    $Entropy = [Text.Encoding]::UTF8.GetBytes('fultons-offhost-backup-v1')
    $ProtectedKey = [Security.Cryptography.ProtectedData]::Protect(
        [Text.Encoding]::UTF8.GetBytes($Password),
        $Entropy,
        [Security.Cryptography.DataProtectionScope]::CurrentUser
    )
    $ArchiveHash = (Get-FileHash -Algorithm SHA256 $StagedArchive).Hash.ToLowerInvariant()
    $ManifestHash = (
        Get-FileHash -Algorithm SHA256 (Join-Path $Downloaded 'manifest.json')
    ).Hash.ToLowerInvariant()

    $FinalArchive = Join-Path $Destination ($Base + '.7z')
    Move-Item -LiteralPath $StagedArchive -Destination $FinalArchive
    [IO.File]::WriteAllText(
        (Join-Path $Destination ($Base + '.key.dpapi')),
        [Convert]::ToBase64String($ProtectedKey),
        [Text.Encoding]::ASCII
    )
    $Metadata = [ordered]@{
        schema = 1
        created_utc = (Get-Date).ToUniversalTime().ToString('o')
        source_host = $Server
        source_backup = $BackupName
        archive = Split-Path $FinalArchive -Leaf
        archive_sha256 = $ArchiveHash
        manifest_sha256 = $ManifestHash
        encryption = '7z AES-256 with encrypted headers'
        key_protection = 'Windows DPAPI CurrentUser'
        verification = 'archive test, clean extraction, backup_manager verify'
    }
    [IO.File]::WriteAllText(
        (Join-Path $Destination ($Base + '.json')),
        ($Metadata | ConvertTo-Json -Depth 3),
        [Text.UTF8Encoding]::new($false)
    )
    Write-Output "Created and restore-verified off-host copy: $FinalArchive"
}
finally {
    Remove-TaskTemporaryDirectory $Work 'fultons-offhost-'
    Remove-TaskTemporaryDirectory $Restore 'fultons-offhost-restore-'
}
