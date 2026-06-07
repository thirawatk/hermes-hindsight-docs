# Kavita + OneDrive Sync Setup

**Last Updated:** 2026-06-07
**CT:** 404 (autocaliweb)
**Purpose:** Sync eBook library from OneDrive to local storage for Kavita

## Architecture

```
OneDrive (Personal)
  └── Personal_stuff/e-book/          (7.7GB, 580 files)
        │
        │  rclone sync (every 6h)
        ▼
CT 404 — /mnt/calibre/library/       (local SSD)
        │
        │  bind mount
        ▼
Kavita Docker — /books/              (container internal)
```

## Current Status

- **Kavita version:** 0.9.0.2 (upgraded from 0.8.4 on 2026-06-07)
- **rclone version:** 1.74.2
- **Library:** 7.7GB, 580 files — fully synced
- **OPDS:** Working at `/api/opds/{apiKey}` (path format, changed in 0.9.x)

## Configuration

### rclone Config (`/root/.config/rclone/rclone.conf`)

```ini
[onedrive]
type = onedrive
token = {"access_token":"...","token_type":"Bearer","refresh_token":"...","expiry":"...","expires_in":3599}
drive_id = 847FBA794A95EBF0
drive_type = personal
```

### Cron Job (`/etc/cron.d/rclone-onedrive-sync`)

```cron
0 */6 * * * root /usr/bin/rclone sync onedrive:Personal_stuff/e-book/ /mnt/calibre/library --transfers 4 --checkers 8 --log-file /var/log/rclone-sync.log --log-level INFO 2>&1
```

### Docker Mount

```yaml
volumes:
  - /opt/kavita/data:/kavita/config
  - /mnt/calibre/library:/books
```

## Access

- **Web UI:** https://kavita.271224.xyz
- **Login:** lottez / Th!2awatKVT
- **Caddy:** `kavita.271224.xyz` → `10.10.20.44:5000`
- **OPDS API Key:** `72900210-ab5d-4d67-95ed-df695109e070`

## OPDS (v0.9.x)

**OPDS URL:** `https://kavita.271224.xyz/api/opds/72900210-ab5d-4d67-95ed-df695109e070`

| Version | Route Format |
|---------|-------------|
| 0.8.x | `/api/opds?apiKey=<key>` (query param) |
| 0.9.x | `/api/opds/<key>` (path param) |

Root catalog links: on-deck, recently-updated, recently-added, reading-list, want-to-read, libraries, collections, search

## Reading Progress

**OPD-PS (Progress Sync):** NOT SUPPORTED. Kavita's OPDS feed is read-only. Moon Reader cannot write progress back to Kavita.

**Pragmatic setup:** Kavita as book library (OPDS download), Moon Reader Google Drive sync for progress between Moon devices.

## Notes

- rclone v1.74.2 requires `drive_id` for OneDrive personal accounts
- Token JSON may be URL-encoded (%24%24 = $$) — decode with `urllib.parse.unquote()` first
- Write rclone config directly to file, NOT via `rclone config update` (re-triggers OAuth)
- Library scan: `POST /api/Library/scan?libraryId=1` with JWT Bearer token
- JWT token: `POST /api/Account/login` with username/password
- Upgrade process: `docker pull` → `docker stop/rm` → `docker run` (data persists via bind mount)

## Troubleshooting

### Sync not running
```bash
cat /etc/cron.d/rclone-onedrive-sync
service cron status
ps aux | grep rclone
tail -f /var/log/rclone-sync.log
```

### Kavita not showing new books
```bash
ssh root@10.10.20.11 "pct exec 404 -- bash -c 'TOKEN=\$(curl -s -X POST http://localhost:5000/api/Account/login -H \"Content-Type: application/json\" -d \"{\"username\":\"lottez\",\"password\":\"Th!2awatKVT\"}\" | python3 -c \"import sys,json; print(json.load(sys.stdin)[\\\"token\\\"])\"); curl -s -X POST http://localhost:5000/api/Library/scan?libraryId=1 -H \"Authorization: Bearer \$TOKEN\"'"
```
