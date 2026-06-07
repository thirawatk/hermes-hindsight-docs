# Kavita eBook Server — Deployment Reference

## Overview
Kavita replaced Calibre-Web Automated (CWA) on CT 404. Docker-based, port 5000, OPDS support for Moon Reader.

## Deployment Details

| | |
|---|---|
| **CT** | 404 (Debian, 1 core, 2GB RAM, 6GB NVMe) |
| **Docker** | `jvmilazz0/kavita:0.9.0.2` (upgraded 2026-06-07) |
| **Port** | 5000 |
| **Data** | `/opt/kavita/data` → `/kavita/config` |
| **Library** | `/mnt/calibre/library` → `/books` (read-write) |
| **Caddy** | `kavita.271224.xyz` → `10.10.20.44:5000` |
| **DNS** | `kavita.271224.xyz.lan` → `10.10.20.44` |
| **Admin** | Created via web UI first-run wizard |

## OneDrive Sync Setup (rclone on CT 404)

### Token Processing
The token JSON from `rclone authorize` may be URL-encoded (`%24%24` = `$$`). Decode first:
```python
import urllib.parse, base64, json
token_b64 = urllib.parse.unquote(token_b64_encoded)
missing_padding = len(token_b64) % 4
if missing_padding:
    token_b64 += '=' * (4 - missing_padding)
token_json = base64.b64decode(token_b64).decode()
token_data = json.loads(token_json)
inner_token = token_data["token"]
```

### rclone 1.74 Requires drive_id
rclone 1.74+ needs `drive_id` for OneDrive personal accounts. Get via Graph API:
```python
inner = json.loads(inner_token)
req = urllib.request.Request(
    "https://graph.microsoft.com/v1.0/me/drive",
    headers={"Authorization": f"Bearer {inner['access_token']}"}
)
drive_info = json.loads(urllib.request.urlopen(req).read())
# drive_info["id"] = drive_id for config
```

### Write Config Directly — NOT via `rclone config update`
`rclone config update` re-triggers the OAuth flow. Write the config file directly:
```ini
[onedrive]
type = onedrive
token = {"access_token":"...","token_type":"Bearer","refresh_token":"..."}
drive_id = <DRIVE_ID>
drive_type = personal
```

### Transfer Config to CT via pve1
`pct push` from the Hermes host fails for local files. Must go through pve1:
```bash
scp /tmp/rclone.conf root@pve1:/tmp/
ssh root@pve1 "pct push 404 /tmp/rclone.conf /root/.config/rclone/rclone.conf"
```

### Sync + Cron
```bash
# OneDrive path is Personal_stuff/e-book/ (NOT Calibre_Library)
rclone sync onedrive:Personal_stuff/e-book/ /mnt/calibre/library/ --transfers 8 --checkers 8 -P

# /etc/cron.d/rclone-onedrive-sync — every 6 hours
0 */6 * * * root /usr/bin/rclone sync onedrive:Personal_stuff/e-book/ /mnt/calibre/library/ --transfers 8 --log-file /var/log/rclone-sync.log --log-level INFO 2>&1
```

## Known Issues

### Library Scan via API
Kavita's library scan via API works:
```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/Account/login -H 'Content-Type: application/json' -d '{"username":"lottez","password":"Th!2awatKVT"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
curl -s -X POST "http://localhost:5000/api/Library/scan?libraryId=1" -H "Authorization: Bearer $TOKEN"
```

### Library Creation via DB
Direct DB manipulation works for creating libraries:
```python
import sqlite3
conn = sqlite3.connect('/opt/kavita/data/kavita.db')
c = conn.cursor()
c.execute("INSERT INTO Library (Name, Type, ...) VALUES (?, 0, ...)")
c.execute("INSERT INTO FolderPath (Path, LibraryId) VALUES (?, ?)", ("/books", lib_id))
conn.commit()
```

### Fresh DB Reset
To reset: `docker stop kavita && rm -f /opt/kavita/data/kavita.db* && docker start kavita`

## Migration from CWA

1. Stopped CWA services (Apache2 + Python process)
2. Installed Docker on CT 404
3. Deployed Kavita container with existing Calibre library bind-mount
4. Updated Caddy config: replaced `calibre.271224.xyz` block with `kavita.271224.xyz`
5. Added DNS record via Technitium API
6. Snapshot CT 404 before changes (rollback ready at `ssd-vault-backup`)

## OPDS for Moon Reader

**Route format changed in v0.9.x:**

| Version | OPDS URL Format |
|---------|----------------|
| 0.8.x (broken) | `/api/opds?apiKey=<key>` — crashes with 500 (locale lookup bug) |
| 0.9.x (working) | `/api/opds/<apiKey>` — API key is a path segment, NOT a query param |

Working OPDS URL:
```
https://kavita.271224.xyz/api/opds/72900210-ab5d-4d67-95ed-df695109e070
```

API key is in `AspNetUsers.ApiKey` column of `/kavita/config/kavita.db`. Extract via:
```bash
ssh root@10.10.20.11 "pct exec 404 -- docker cp kavita:/kavita/config/kavita.db /tmp/kavita.db && python3 -c \"
import sqlite3; conn=sqlite3.connect('/tmp/kavita.db'); c=conn.cursor()
c.execute('SELECT UserName, ApiKey FROM AspNetUsers'); [print(r) for r in c.fetchall()]
conn.close()
\""
```

**⚠️ DB copy is required** — `sqlite3` is NOT in the Kavita container. Always `docker cp` the DB out first, then query from the CT host.

Moon Reader Pro → Add OPDS catalog → URL above (no username/password needed).

### Upgrade Procedure (0.8.4 → 0.9.x)

1. Pull latest: `docker pull jvmilazz0/kavita:latest`
2. Stop old: `docker stop kavita && docker rm kavita`
3. Start new (same mounts + env):
   ```bash
   docker run -d --name kavita --restart unless-stopped \
     -e TZ=Asia/Bangkok -p 5000:5000 \
     -v /opt/kavita/data:/kavita/config \
     -v /mnt/calibre/library:/books \
     jvmilazz0/kavita:latest
   ```
4. Wait for healthy: `docker ps --format "table {{.Names}}\t{{.Status}}" | grep kavita`
5. Test OPDS: `curl -s "http://localhost:5000/api/opds/<apiKey>" | head -5` — should return XML `<feed>`, not HTML

**Data persists** — `/opt/kavita/data` bind-mount preserves config, DB, and all user data across container recreations.

## Shell Quoting Pitfall: Nested SSH → pct exec → bash -c

When running complex commands (Python, regex, nested quotes) through `ssh root@pve1 "pct exec 404 -- bash -c '...'"`, nested quotes **always** break. Single quotes inside single quotes, escaped double quotes, `$()` expansion — they all fail silently or produce syntax errors.

**Workaround: Base64 encode the entire script and pipe through:**

```python
# Run from buddy CT (hermes-ubuntu)
import subprocess, base64

script = open("local_script.py").read()
encoded = base64.b64encode(script.encode()).decode()
cmd = f"pct exec 404 -- bash -c 'echo {encoded} | base64 -d | python3'"
subprocess.run(["ssh", "-o", "StrictHostKeyChecking=no",
    "root@10.10.20.11", cmd], capture_output=True, timeout=30)
```

From the buddy CT, you must go through pve1 (10.10.20.11) to reach CT 404. Direct SSH to CT 404 fails (no key auth configured). The buddy CT's `~` resolves to `/root/.hermes/profiles/buddy/home/`, not `/root`.

## Moon Reader Pro + Kavita: Sync Limitations

**Moon Reader Pro cannot sync reading progress with Kavita.** This is a hard limitation:

- Kavita's OPDS feed does **not** support OPDS-PS (Progress Sync protocol)
- No `open-access` acquisition links, no progress sync API endpoints
- Moon Reader's OPDS client is read-only (browse + download only)
- The `/api/Device` endpoint exists but returns empty `[]`

**Moon Reader Pro's built-in sync (Moon-to-Moon only):**
| Method | Setup | Notes |
|--------|-------|-------|
| Google Drive | Built-in | Sync positions between Moon Reader instances |
| Dropbox | Built-in | Same |
| WebDAV | Built-in | Works with Nextcloud, any WebDAV server |

**Workarounds for Kavita-native progress tracking:**
- Use Kavita's **web browser reader** for books needing server-side progress
- Switch to **Panels** (Android) which supports Kavita's native API for progress sync
- **ReadSync** (github.com/JediRhymeTrix/readsync) — self-hosted cross-reader progress sync (Moon Reader, KOReader, Calibre, Goodreads)

## What Works Today

- ✅ Browse & download books via OPDS in Moon Reader Pro
- ✅ Reading Lists, Want to Read, On Deck, Recently Updated/Added, Collections
- ✅ OpenSearch search endpoint
- ✅ OneDrive → rclone → local library sync (6h cron)
- ✅ Library scan via web UI
- ❌ Reading progress sync (Moon Reader → Kavita)
- ❌ Highlights/notes sync
- ❌ Multi-device sync via Kavita

## Backup
Library is on ssd-vault (bind-mounted). CT snapshots go to `ssd-vault-backup` storage.
