<#
.SYNOPSIS
    Relocate Claude Desktop's Computer Use VM bundle off the system drive via a directory junction.

.DESCRIPTION
    The Claude Desktop app (Windows MSIX install) stores a multi-GB VHDX-backed sandbox VM at
    %APPDATA%\Claude\vm_bundles\. This script moves that folder to a roomier drive and leaves
    a transparent NTFS directory junction at the original path. Reversible. No admin required.

.PARAMETER Source
    The path to vm_bundles. Defaults to "$env:APPDATA\Claude\vm_bundles".

.PARAMETER DestRoot
    The parent folder on the target drive. The script creates "<DestRoot>\vm_bundles" inside it.
    Defaults to "H:\ClaudeArchive".

.PARAMETER Action
    'move'    - move source to dest and replace source with a junction (default)
    'restore' - reverse: move data back into source path, delete junction
    'inspect' - report current state, make no changes

.EXAMPLE
    .\windows.ps1
    Moves %APPDATA%\Claude\vm_bundles to H:\ClaudeArchive\vm_bundles.

.EXAMPLE
    .\windows.ps1 -DestRoot 'D:\ClaudeArchive' -Action move

.EXAMPLE
    .\windows.ps1 -Action inspect

.EXAMPLE
    .\windows.ps1 -Action restore
#>
[CmdletBinding()]
param(
    [string]$Source = (Join-Path $env:APPDATA 'Claude\vm_bundles'),
    [string]$DestRoot = 'H:\ClaudeArchive',
    [ValidateSet('move','restore','inspect')]
    [string]$Action = 'move'
)

$ErrorActionPreference = 'Stop'

function Test-IsJunction([string]$path) {
    if (-not (Test-Path $path)) { return $false }
    $item = Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    if (-not $item) { return $false }
    return [bool]($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)
}

function Get-JunctionTarget([string]$path) {
    $item = Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    if ($item -and $item.Target) { return $item.Target }
    return $null
}

function Test-VHDXLocked([string]$root) {
    $vhdx = Join-Path $root 'claudevm.bundle\rootfs.vhdx'
    if (-not (Test-Path $vhdx)) { return $false }
    try {
        $fs = [System.IO.File]::Open($vhdx, 'Open', 'Read', 'None')
        $fs.Close()
        return $false
    } catch { return $true }
}

function Get-FolderSizeGB([string]$path) {
    if (-not (Test-Path $path)) { return 0 }
    $sum = (Get-ChildItem $path -Recurse -Force -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
    return [math]::Round(($sum/1GB), 2)
}

function Get-DriveFreeGB([string]$driveLetter) {
    $d = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$driveLetter'"
    if ($d) { return [math]::Round($d.FreeSpace/1GB, 2) }
    return 0
}

function Show-Status {
    Write-Host ""
    Write-Host "Source path: $Source" -ForegroundColor Cyan
    if (-not (Test-Path $Source)) {
        Write-Host "  (does not exist)" -ForegroundColor DarkGray
        return
    }
    $isJunction = Test-IsJunction $Source
    if ($isJunction) {
        $target = Get-JunctionTarget $Source
        Write-Host "  Type:   directory junction" -ForegroundColor Green
        Write-Host "  Target: $target"
        Write-Host ("  Size:   {0} GB (lives on target drive)" -f (Get-FolderSizeGB $Source))
    } else {
        Write-Host "  Type:   real directory" -ForegroundColor Yellow
        Write-Host ("  Size:   {0} GB (lives on source drive)" -f (Get-FolderSizeGB $Source))
    }
    $sourceDrive = (Split-Path -Qualifier $Source)
    Write-Host ("  $sourceDrive drive free: {0} GB" -f (Get-DriveFreeGB $sourceDrive))
}

function Invoke-Move {
    $dest = Join-Path $DestRoot 'vm_bundles'

    if (-not (Test-Path $Source)) {
        Write-Host "Source $Source does not exist. Nothing to move." -ForegroundColor Yellow
        return
    }

    if (Test-IsJunction $Source) {
        $existingTarget = Get-JunctionTarget $Source
        Write-Host "Source is already a junction -> $existingTarget" -ForegroundColor Green
        Write-Host "Nothing to do. Use -Action restore to move data back." -ForegroundColor Green
        return
    }

    if (Test-Path $dest) {
        throw "Destination $dest already exists. Refusing to overwrite. Inspect manually."
    }

    if (Test-VHDXLocked $Source) {
        throw "rootfs.vhdx is locked - Claude Desktop has an active Computer Use VM mounted. Close it and retry."
    }

    $needGB = Get-FolderSizeGB $Source
    $destDrive = (Split-Path -Qualifier $DestRoot)
    $haveGB = Get-DriveFreeGB $destDrive
    if ($haveGB -lt ($needGB + 1)) {
        throw "Destination drive $destDrive has only $haveGB GB free; need at least $($needGB + 1) GB."
    }

    Write-Host "Moving $Source -> $dest" -ForegroundColor Cyan
    Write-Host ("  Bundle size: {0} GB" -f $needGB)

    if (-not (Test-Path $DestRoot)) {
        New-Item -ItemType Directory -Path $DestRoot | Out-Null
        Write-Host "Created $DestRoot"
    }

    $rcArgs = @($Source, $dest, '/E', '/MOVE', '/MT:8', '/R:1', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS')
    $rc = Start-Process -FilePath robocopy -ArgumentList $rcArgs -Wait -PassThru -NoNewWindow
    Write-Host "robocopy exit code: $($rc.ExitCode) (0-7 ok, 8+ error)"
    if ($rc.ExitCode -ge 8) {
        throw "robocopy reported errors. Source folder may be partially emptied. Inspect and rerun."
    }

    if (Test-Path $Source) {
        $remaining = Get-ChildItem $Source -Force -ErrorAction SilentlyContinue
        if ($remaining) {
            throw "Source $Source not empty after /MOVE - aborting before junction creation. Inspect manually."
        }
        Remove-Item $Source -Force
        Write-Host "Removed empty source folder $Source"
    }

    $mklinkOut = cmd /c "mklink /J `"$Source`" `"$dest`""
    Write-Host $mklinkOut

    if (-not (Test-IsJunction $Source)) {
        throw "Junction creation appeared to succeed but $Source is not a reparse point. Investigate."
    }

    Write-Host "Junction created OK" -ForegroundColor Green
    Show-Status
}

function Invoke-Restore {
    if (-not (Test-Path $Source)) {
        Write-Host "Source $Source does not exist. Nothing to restore." -ForegroundColor Yellow
        return
    }

    if (-not (Test-IsJunction $Source)) {
        Write-Host "Source is already a real directory, not a junction. Nothing to restore." -ForegroundColor Yellow
        return
    }

    $target = Get-JunctionTarget $Source
    Write-Host "Junction $Source -> $target" -ForegroundColor Cyan

    if (-not $target -or -not (Test-Path $target)) {
        throw "Junction target $target does not exist. Cannot restore. Delete the junction manually if you want."
    }

    if (Test-VHDXLocked $Source) {
        throw "rootfs.vhdx is locked - Claude Desktop has an active Computer Use VM mounted. Close it and retry."
    }

    $needGB = Get-FolderSizeGB $target
    $sourceDrive = (Split-Path -Qualifier $Source)
    $haveGB = Get-DriveFreeGB $sourceDrive
    if ($haveGB -lt ($needGB + 1)) {
        throw "Source drive $sourceDrive has only $haveGB GB free; need at least $($needGB + 1) GB to restore."
    }

    Write-Host "Removing junction at $Source"
    cmd /c "rmdir `"$Source`"" | Out-Null

    if (Test-Path $Source) {
        throw "Failed to remove junction at $Source."
    }

    Write-Host "Moving $target -> $Source" -ForegroundColor Cyan
    $rcArgs = @($target, $Source, '/E', '/MOVE', '/MT:8', '/R:1', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS')
    $rc = Start-Process -FilePath robocopy -ArgumentList $rcArgs -Wait -PassThru -NoNewWindow
    Write-Host "robocopy exit code: $($rc.ExitCode)"
    if ($rc.ExitCode -ge 8) {
        throw "robocopy reported errors during restore. Inspect manually."
    }

    if ((Test-Path $target) -and -not (Get-ChildItem $target -Force -ErrorAction SilentlyContinue)) {
        Remove-Item $target -Force
    }

    Write-Host "Restore complete" -ForegroundColor Green
    Show-Status
}

switch ($Action) {
    'inspect' { Show-Status }
    'move'    { Invoke-Move }
    'restore' { Invoke-Restore }
}
