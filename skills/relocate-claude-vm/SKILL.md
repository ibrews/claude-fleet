---
name: relocate-claude-vm
description: Move the Claude Desktop "Computer Use" sandbox VM bundle (typically 11-13 GB at %APPDATA%\Claude\vm_bundles on Windows) off the system drive to a roomier disk via a directory junction. Transparent to Claude Desktop, reversible. Use when the system drive is low on space and a disk scan shows vm_bundles as a top consumer. Also handles the restore (move back) and dry-run inspection paths.
---

# Relocate Claude Desktop's Computer Use VM bundle

The Claude Desktop app downloads a multi-GB sandboxed VM image to power its local Computer Use / code-execution features. The app provides no in-app setting to relocate it. On a system drive that's already tight, this bundle can be the single biggest space consumer — bigger than the user's Documents folder.

This skill moves the bundle to a target drive and leaves a directory junction (Windows) or symbolic link (macOS — not yet implemented) at the original location, so Claude Desktop sees the same path it expects.

## When to use this skill

- A disk scan shows `C:\Users\<user>\AppData\Roaming\Claude\vm_bundles\` is a top consumer (typically 11-13 GB)
- The system drive is below 15% free and you've already cleared regenerable caches (npm, pip, Windows Update, temp)
- The user has at least 25 GB free on another local NTFS volume (need room for the move + headroom)

Do **not** use this skill when:
- Claude Desktop is mid-update — finish the update first; MSIX state during an update is brittle
- The VHDX is currently in use by an active Computer Use session — the move will fail (the script checks for this and aborts cleanly)
- The destination is a network drive, removable drive, or non-NTFS volume — VHDX-backed VMs need local fixed NTFS storage

## What the bundle actually contains

Inside `%APPDATA%\Claude\vm_bundles\claudevm.bundle\` you'll typically find:

| File | Typical size | Purpose |
|---|---|---|
| `rootfs.vhdx` | ~9 GB | The mounted VM root filesystem image (QEMU VHDX v2 format — magic bytes `vhdxfile`) |
| `sessiondata.vhdx` | ~0.5 GB | Per-session writable disk |
| `smol-bin.vhdx` | ~35 MB | Small helper image |
| `initrd`, `vmlinuz` | ~180 MB combined | Linux kernel + initial ramdisk |
| `*.zst` archives | ~2.4 GB | Compressed source bundles (used to re-extract the VHDX if corrupted) |
| `.*.origin` files | tiny | Manifest sidecars referencing the source archives |

The conversation history people often assume is in this folder is **not** here — Claude Desktop conversations live server-side at Anthropic, with only a small (~250 MB) Electron cache locally in `Cache`, `Code Cache`, etc.

## How to invoke

Pass the source path, destination root, and operation. Defaults shown:

```powershell
# Move (default operation)
& "$env:USERPROFILE\.claude\skills\relocate-claude-vm\windows.ps1" `
    -Source 'C:\Users\Sam\AppData\Roaming\Claude\vm_bundles' `
    -DestRoot 'H:\ClaudeArchive' `
    -Action move

# Inspect only (no changes)
& "$env:USERPROFILE\.claude\skills\relocate-claude-vm\windows.ps1" -Action inspect

# Restore (reverse: move back from junction target, remove junction)
& "$env:USERPROFILE\.claude\skills\relocate-claude-vm\windows.ps1" -Action restore
```

The script:
1. Verifies the source exists and is not already a junction (idempotent — skips if it's already moved)
2. Tests that `rootfs.vhdx` isn't locked (would mean an active Computer Use session)
3. Creates the destination
4. Runs `robocopy /E /MOVE /MT:8` for the actual transfer (multi-threaded, resumable, native)
5. Deletes the now-empty source folder
6. Creates a directory junction at the original path (`mklink /J`, no admin needed)
7. Verifies the junction resolves and the VHDX is still readable
8. Prints before/after free space on the source drive

## How to verify the move worked

After the script completes:

- `Get-Item C:\Users\<user>\AppData\Roaming\Claude\vm_bundles` should show `Attributes: Directory, ReparsePoint` and a `Target` pointing to the destination
- The first 16 bytes of `rootfs.vhdx` read through the original path should start with `vhdxfile` (76 68 64 78 66 69 6C 65)
- Claude Desktop should launch and operate normally. The first invocation of Computer Use after the move will mount the VM from the new location — there is no user-visible difference
- C: free space should be higher by approximately the bundle size (11-13 GB typical)

## Restore (move back)

If you need to undo this — e.g., you've replaced your big secondary drive and want everything on C: again — invoke with `-Action restore`. The script will refuse to restore if the destination drive doesn't have enough free space on C: to receive the bundle back.

## Edge cases this skill handles

- **Already moved (idempotent)** — if `vm_bundles` is already a junction, `inspect` reports the current target and `move` is a no-op
- **VHDX locked** — abort cleanly with a clear error before touching anything
- **Robocopy partial failure** — robocopy returns codes 0-7 for success, 8+ for error; we abort junction creation on 8+, leaving robocopy's `/MOVE` state recoverable on retry
- **Destination already exists** — refuse to overwrite

## Platforms

- **Windows**: implemented. Uses NTFS directory junctions (`mklink /J`) — no admin required, works across local drives
- **macOS**: not yet implemented. Claude Desktop on macOS stores its sandbox image at `~/Library/Application Support/Claude/vm_bundles/` (path subject to verification). The macOS variant would use `ln -s` symbolic links and `rsync -a --remove-source-files`. To be added in `macos.sh` when first needed.

## Why a junction and not a symbolic link

On Windows, symbolic links to directories require admin privileges or Developer Mode (`SeCreateSymbolicLinkPrivilege`). Directory junctions don't — they're a different reparse-point type that only works for local directories on the same machine, which is exactly our case. From the perspective of nearly all applications (including Electron apps like Claude Desktop), junctions are indistinguishable from real directories.

## Related

- KB runbook with incident-level detail: `~/knowledge/intelligence/runbooks/relocate-claude-vm.md`
- Sister runbook for Claude Desktop MSIX corruption issues: `~/knowledge/intelligence/runbooks/claude-desktop-corruption-windows.md`
- Fleet repo this skill is published from: https://github.com/ibrews/claude-fleet
