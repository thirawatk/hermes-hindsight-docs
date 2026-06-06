# Kavita + OneDrive Sync Setup

**Date:** 2026-06-06
**CT:** 404 (autocaliweb)
**Purpose:** Sync eBook library from OneDrive to local storage for Kavita

## Architecture

```
OneDrive (Personal)
  └── Personal_stuff/e-book/          (7.9GB, 580 files)
        │
        │  rclone sync (every 6h)
        ▼
CT 404 — /mnt/calibre/library/       (local SSD)
        │
        │  bind mount
        ▼
Kavita Docker — /books/              (container internal)
```

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

## Notes

- rclone v1.74.2 requires `drive_id` for OneDrive personal accounts
- Get drive_id via: `GET https://graph.microsoft.com/v1.0/me/drive` with Bearer token
- Token JSON may be URL-encoded (%24%24 = $$) — decode with `urllib.parse.unquote()` first
- Write rclone config directly to file, NOT via `rclone config update` (re-triggers OAuth)
- Kavita v0.8.4.2, update to v0.9.0.x available
- Library scan triggered via API: `POST /api/Library/scan?libraryId=1` with JWT Bearer token
- JWT token obtained from: `POST /api/Account/login` with username/password

## Troubleshooting

### Sync not running
```bash
# Check cron
cat /etc/cron.d/rclone-onedrive-sync
service cron status

# Check rclone process
ps aux | grep rclone

# Check logs
tail -f /var/log/rclone-sync.log
```

### Kavita not showing new books
```bash
# Trigger manual scan via API
TOKEN=$(curl -s -X POST http://localhost:5000/api/Account/login \
  -H "Content-Type: application/json" \
  -d '{"username":"lottez","password":"Th!2awatKVT"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

curl -s -X POST http://localhost:5000/api/Library/scan?libraryId=1 \
  -H "Authorization: Bearer $TOKEN"
```

### rclone token expired
```bash
# Re-authorize on local machine:
rclone authorize "onedrive" "eyJkcml2ZV90eXBlIjoicGVyc29uYWwifQ"
# Then update token in /root/.config/rclone/rclone.conf
```
