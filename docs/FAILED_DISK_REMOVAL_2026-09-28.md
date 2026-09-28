# Failed disk removal runbook — 28 September 2026

This runbook identifies the retired disk precisely and records the checks needed
before and after physical removal. It does not authorize remote power-off or
hardware changes.

## Exact device

| Property | Value |
|---|---|
| Current Linux device | `/dev/sdd` |
| Capacity | 1.8 TiB (marketed as 2 TB) |
| Transport | USB |
| Model | `WDC WD20EARX-22PASB0` |
| Serial | `WD-WCAZAA791731` |
| WWN | `0x50014ee25baf4ae9` |
| Filesystem | ext4 on the whole device |
| Filesystem UUID | `36dc39ba-aa49-449a-a45f-fe062ceb75a3` |
| Stable USB identifier | `usb-WD_Ext_HDD_1021_5743415A4141373931373331-0:0` |

Smartd continued to report five pending sectors and four offline-uncorrectable
sectors at 10:38 UTC on 28 September. The disk should not return to service.

## Dependency proof

At the final read-only check:

- neither `/dev/sdd` nor its filesystem was mounted;
- the kernel `holders` directory was empty and no visible process file descriptor
  referenced the device;
- it was not swap and no running Docker container mounted it;
- active mergerfs branches were `disk2`, `disk4` and `localpool`; `/disk5` was not
  a branch;
- `/etc/fstab` still contained this stale, non-automatic entry:

  ```text
  UUID=36dc39ba-aa49-449a-a45f-fe062ceb75a3 /disk5 ext4 noauto,nofail,x-systemd.device-timeout=10 0 2
  ```

`noauto,nofail` means that entry does not currently mount the disk or block boot,
but it should be removed or commented when the disk is retired.

## Shutdown-first removal

Perform these steps with local console and physical access:

1. Confirm Fulton, Jellyfin, Pi-hole and Traefik are healthy and that the latest
   Fulton and Jellyfin backups still verify.
2. Remove or comment only the fstab line containing UUID
   `36dc39ba-aa49-449a-a45f-fe062ceb75a3`, then run
   `sudo findmnt --verify --verbose`. Do not alter the `/disk2` or `/disk4`
   entries.
3. Run `sudo systemctl poweroff` and wait until the host and USB disk are fully
   powered down.
4. Disconnect the external WD disk matching serial `WD-WCAZAA791731`. Do not
   disconnect the active `/dev/sdb` or `/dev/sdc` USB disks.
5. Start the host and complete the post-boot checks below.

## Post-boot checks

```bash
lsblk -dn -o NAME,SIZE,MODEL,SERIAL,WWN,TRAN
findmnt --target /disk2
findmnt --target /disk4
findmnt --target /srv/storage
docker ps --format 'table {{.Names}}\t{{.Status}}'
systemctl --user is-active fultons-backup.timer fultons-resilience.timer jellyfin-backup.timer
curl --fail --silent --show-error https://fultons-quiz.co.uk/api/health
journalctl -b -u smartmontools.service -u smartd.service --no-pager
```

The retired serial and WWN should be absent, `/disk2`, `/disk4` and
`/srv/storage` should be mounted, all four containers should be healthy/running,
all three user timers should be active, and smartd should no longer emit the
half-hourly `/dev/sdd` sector warnings.
