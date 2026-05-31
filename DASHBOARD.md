# Hermes Dashboard — Complete Deployment Guide

> **Verified:** 2026-05-31 — All panels rendering, SPA working, kanban boards showing live data.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [CT 501 — Dashboard Backend (FastAPI)](#ct-501--dashboard-backend-fastapi)
- [CT 103 — Caddy Reverse Proxy](#ct-103--caddy-reverse-proxy)
- [Grafana Integration](#grafana-integration)
- [Hermes SPA (hermes.271224.xyz)](#hermes-spa-hermes271224xyz)
- [Kanban Board Display](#kanban-board-display)
- [Directory Structure](#directory-structure)
- [Service Files Reference](#service-files-reference)
- [Deployment Steps (Reproduce from Scratch)](#deployment-steps-reproduce-from-scratch)
- [Troubleshooting](#troubleshooting)

---

## Overview

The Hermes Dashboard is a monitoring and control panel spread across two LXC containers:

| Component | CT | IP | Port | Purpose |
|-----------|----|----|------|---------|
| **Dashboard Backend** | 501 (monitor) | 10.10.20.51 | 8080 | FastAPI app serving HTML pages + JSON API |
| **Grafana** | 501 (monitor) | 10.10.20.51 | 3000 | Visualization with iframe panels embedding dashboard |
| **Caddy** | 103 | 10.10.20.23 | 80/443 | Reverse proxy with HTTPS, routes all `*.271224.xyz` domains |
| **Hermes Agent** | 301 (hermes-ubuntu) | 10.10.20.31 | 9119 | Hermes Dashboard SPA + Kanban API |
| **Hindsight API** | 301 (hermes-ubuntu) | 10.10.20.31 | 8888 | Memory system backend (PostgreSQL) |

### Public Access (via Cloudflare Tunnel)

| Domain | Routes To | Purpose |
|--------|-----------|---------|
| `monitor.271224.xyz` | CT 103 → CT 501:3000 (Grafana) + CT 501:8080 (`/dashboard/*`) | Main monitoring page |
| `hermes.271224.xyz` | CT 103 → CT 301:9119 (direct) | Hermes Dashboard SPA standalone |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           INTERNET                                          │
│                              │                                              │
│                    Cloudflare Tunnel (CNAME *.271224.xyz)                   │
│                              │                                              │
└──────────────────────────────┼──────────────────────────────────────────────┘
                               │
┌──────────────────────────────┼──────────────────────────────────────────────┐
│                        CT 103 (Caddy) 10.10.20.23                           │
│                              │                                              │
│  ┌───────────────────────────┼─────────────────────────────────────────┐    │
│  │  monitor.271224.xyz      │                                         │    │
│  │  ┌─────────────────────┐  │                                         │    │
│  │  │ /dashboard/*        ├──┼──► CT 501:8080 (strip_prefix /dashboard)│    │
│  │  └─────────────────────┘  │                                         │    │
│  │  ┌─────────────────────┐  │                                         │    │
│  │  │ everything else     ├──┼──► CT 501:3000 (Grafana)               │    │
│  │  └─────────────────────┘  │                                         │    │
│  └───────────────────────────┼─────────────────────────────────────────┘    │
│                              │                                              │
│  ┌───────────────────────────┼─────────────────────────────────────────┐    │
│  │  hermes.271224.xyz       │                                         │    │
│  │  ALL traffic             ├──┼──► CT 301:9119 (direct, no proxy)     │    │
│  └───────────────────────────┼─────────────────────────────────────────┘    │
│                              │                                              │
└──────────────────────────────┼──────────────────────────────────────────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         │                     │                     │
         ▼                     ▼                     ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ CT 501 (monitor)│  │ CT 301 (hermes) │  │ Other CTs       │
│ 10.10.20.51     │  │ 10.10.20.31     │  │                 │
│                 │  │                 │  │ CT 102: DNS     │
│ Grafana :3000   │  │ Hermes SPA :9119│  │ CT 402: Paperless│
│ FastAPI  :8080  │  │ Hindsight  :8888│  │ CT 403: Joplin  │
│                 │  │ Kanban API      │  │ CT 404: CWA     │
│ SSH queries ────┼──►│ 5 gateways      │  │ CT 103: Caddy   │
│ to CT 301       │  │ Kanban DB       │  └─────────────────┘
└─────────────────┘  └─────────────────┘
```

### Data Flow

```
Browser → monitor.271224.xyz/dashboard/kanban
  → Caddy (CT 103) strips /dashboard
  → CT 501:8080 /kanban
  → FastAPI renders kanban.html template
  → JS fetch('api/kanban/boards')  (relative path!)
  → /api/kanban/boards handler in main.py
  → services.kanban.get_boards()
  → SSH to CT 301 → query SQLite DBs
  → Return JSON to browser
```

---

## CT 501 — Dashboard Backend (FastAPI)

### Service

```
Service:  hermes-dashboard.service (systemd)
Path:    /opt/hermes-dashboard/
Main:    /opt/hermes-dashboard/main.py
Port:    8080
```

### Key Design Decisions

1. **No SPA proxy** — CT 501 serves ONLY the monitoring pages (Overview, Hindsight, Kanban). The SPA lives on CT 301:9119 and is accessed directly via `hermes.271224.xyz`.

2. **Relative JS API paths** — All dashboard page templates use `fetch('api/gateway')` (relative), NOT `fetch('/api/gateway')` (absolute). This is critical because the pages are served behind Caddy's `strip_prefix /dashboard`. Browser resolves relative to current URL path:
   - `monitor.271224.xyz/dashboard/` + `fetch('api/gateway')` = `monitor.271224.xyz/dashboard/api/gateway`
   - Caddy strips `/dashboard` → CT 501 gets `/api/gateway` → correct handler

3. **SSH data collection** — CT 501 has no direct access to Hermes/Hindsight data. All data is collected via SSH to CT 301 using Python one-liners encoded in base64 (avoids shell quoting issues).

4. **Read-only** — The dashboard only reads state. There are no write endpoints (except Hindsight recall search which is idempotent).

### API Routes (specific-first, catch-all-last)

```python
# Specific routes
GET  /api/gateway          # Gateway process status
GET  /api/storage           # rpool + ssd-vault usage
GET  /api/hindsight/health  # Hindsight API health
GET  /api/hindsight/banks   # All banks with stats
POST /api/hindsight/recall/{bank_id}  # Search memories
GET  /api/kanban/boards     # List all boards
GET  /api/kanban/tasks/{board_slug}   # Tasks per board

# Catch-all MUST be registered LAST
GET  /api/{path:path}       # 404 for unknown routes
```

> **CRITICAL:** The catch-all `/api/{path:path}` route MUST be the last route registered in FastAPI. If placed before specific routes, it intercepts them.

### Service Modules

| File | Purpose |
|------|---------|
| `services/__init__.py` | Re-exports all service functions |
| `services/hermes.py` | Gateway status + storage + Hindsight health + bank stats (SSH to CT 301) |
| `services/hindsight.py` | Hindsight bank list, recall, health, version (SSH to CT 301) |
| `services/kanban.py` | Board list + task list (SSH to CT 301, queries SQLite via base64-encoded Python) |

### Kanban Service Details

The kanban service handles two database locations:

| DB | Path | Content |
|----|------|---------|
| Default board | `/root/.hermes/kanban.db` | Financial Services board (shared across all profiles) |
| Board directories | `/root/.hermes/kanban/boards/<slug>/kanban.db` | Per-profile boards (e.g. buddy-monitor) |

**Query method:** Python script encoded in base64, piped through SSH:
```python
# On CT 510, the kanban service does:
import base64
py_script = """import sqlite3, json
conn = sqlite3.connect("/root/.hermes/kanban.db")
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT status, COUNT(*) as cnt FROM tasks WHERE status != 'archived' GROUP BY status")
result = [dict(r) for r in c.fetchall()]
print(json.dumps(result))
conn.close()"""
encoded = base64.b64encode(py_script.encode()).decode()
ssh_run(f"echo '{encoded}' | base64 -d | python3")
```

**Board display names** are read from `board.json` metadata:
```json
{
  "slug": "buddy-monitor",
  "name": "Monitor Services",
  "description": "",
  "icon": "",
  "color": "",
  "default_workdir": null,
  "created_at": 1780122402,
  "archived": false
}
```

If no `board.json` exists, falls back to slug-based name (e.g. "Buddy Monitor" from "buddy-monitor").

---

## CT 103 — Caddy Reverse Proxy

### Current Caddyfile (Final)

```caddy
(cloudflare_tls) {
    tls {
        issuer acme {
            dns cloudflare {env.CLOUDFLARE_API_TOKEN}
            resolvers 1.1.1.1
        }
    }
}

# ... (other site blocks: caddy, router, ap1, ap2, dns, pve1, etc.) ...

monitor.271224.xyz {
    import cloudflare_tls
    handle /dashboard/* {
        uri strip_prefix /dashboard
        reverse_proxy http://monitor.271224.xyz.lan:8080
    }
    reverse_proxy http://monitor.271224.xyz.lan:3000
}

hermes.271224.xyz {
    import cloudflare_tls
    reverse_proxy http://10.10.20.31:9119
}
```

### Routing Logic

**`monitor.271224.xyz`:**
1. Requests to `/dashboard/*` → strip prefix → CT 501:8080 (FastAPI)
2. Everything else → CT 501:3000 (Grafana)

**`hermes.271224.xyz`:**
1. ALL requests → CT 301:9119 (Hermes Dashboard SPA direct)

### DNS

Wildcard CNAME `*.271224.xyz` → Cloudflare Tunnel covers all subdomains. No per-subdomain DNS records needed.

### HTTPS

Cloudflare API token in `/etc/caddy/.env` on CT 103. Caddy uses ACME DNS-01 challenge through Cloudflare. TLS certs auto-provisioned and renewed.

---

## Grafana Integration

### Container

- **Docker container** on CT 501, port 3000
- **Custom config:** `/opt/monitoring/grafana.ini` with:
  - `GF_SECURITY_ALLOW_EMBEDDING=true`
  - `GF_PANELS_DISABLE_SANITIZE_HTML=true`

### "Hermes Overview" Dashboard

- **UID:** `hermes-overview`
- **URL:** `https://monitor.271224.xyz/d/hermes-overview/hermes-overview`

### Panels

| # | Panel Title | iframe URL |
|---|-------------|------------|
| 1 | Dashboard — Overview | `https://monitor.271224.xyz/dashboard/` |
| 2 | Hermes Dashboard | `https://hermes.271224.xyz/` |
| 3 | Dashboard — Hindsight Browser | `https://monitor.271224.xyz/dashboard/hindsight` |
| 4 | Dashboard — Kanban | `https://monitor.271224.xyz/dashboard/kanban` |

---

## Hermes SPA (hermes.271224.xyz)

The Hermes Dashboard SPA runs natively on CT 301:9119. It's a separate FastAPI application built into Hermes Agent (`hermes dashboard` command). It's NOT proxied through CT 501 — Caddy sends traffic directly to CT 301:9119.

### Why Separate?

The SPA makes API calls to `/api/*` on its own origin (`hermes.271224.xyz`). If it were served through CT 501 proxy, absolute `/api/*` calls would hit CT 501 instead of CT 301. Rather than adding proxy hacks, giving the SPA its own domain is the clean solution.

---

## Kanban Board Display

The Kanban page (`/kanban`) shows boards from CT 301's SQLite databases.

### Active Boards

| Slug | Display Name | DB Location | Purpose |
|------|-------------|-------------|---------|
| `default` | Financial Services | `/root/.hermes/kanban.db` | Shared board for all financial analysis tasks |
| `buddy-monitor` | Monitor Services | `/root/.hermes/kanban/boards/buddy-monitor/kanban.db` | Tasks between buddy (orchestrator) and monitor (worker) |

### Task Filtering

Tasks are filtered by `status != 'archived'` (NOT `archived_at IS NULL` — there is no `archived_at` column in the schema). Archived tasks are those with `status = 'archived'`.

---

## Directory Structure

### CT 501 (`/opt/hermes-dashboard/`)

```
hermes-dashboard/
├── main.py                  # FastAPI app — routes, templates
├── services/
│   ├── __init__.py          # Re-exports
│   ├── hermes.py            # Gateway status, storage, bank stats
│   ├── hindsight.py         # Hindsight banks, recall, health
│   └── kanban.py            # Board list, task list (SSH to CT 301)
├── templates/
│   ├── base.html            # Pico CSS base template
│   ├── overview.html        # Overview page
│   ├── hermes.html          # Hermes gateway status page
│   ├── hindsight.html       # Hindsight browser page
│   └── kanban.html          # Kanban board page
└── static/                  # (empty - Pico CSS loaded from base.html CDN)
```

### CT 301 (`/root/.hermes/kanban/`)

```
kanban/
├── kanban.db                # Default board ("Financial Services")
└── boards/
    ├── buddy-monitor/
    │   ├── kanban.db        # Monitor Services board
    │   └── board.json       # Metadata (display name, etc.)
    └── default/
        └── board.json       # Metadata for default board
```

---

## Service Files Reference

### CT 501 systemd — `hermes-dashboard.service`

```ini
[Unit]
Description=Hermes Monitoring Dashboard
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/hermes-dashboard
ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### CT 301 — Hermes Dashboard (SPA)

Started via `hermes dashboard` command, serves on port 9119. The SPA is part of the Hermes Agent package and doesn't need separate service configuration.

---

## Deployment Steps (Reproduce from Scratch)

### 1. CT 501 — Dashboard Backend

```bash
# Create directory
mkdir -p /opt/hermes-dashboard/services /opt/hermes-dashboard/templates /opt/hermes-dashboard/static

# Install FastAPI
pip install fastapi uvicorn jinja2 starlette

# Copy all service files and templates (from this repo)
# ...

# Start
uvicorn main:app --host 0.0.0.0 --port 8080
```

### 2. CT 103 — Caddy

Add to `/etc/caddy/Caddyfile`:
```caddy
monitor.271224.xyz {
    import cloudflare_tls
    handle /dashboard/* {
        uri strip_prefix /dashboard
        reverse_proxy http://monitor.271224.xyz.lan:8080
    }
    reverse_proxy http://monitor.271224.xyz.lan:3000
}

hermes.271224.xyz {
    import cloudflare_tls
    reverse_proxy http://10.10.20.31:9119
}
```

Apply:
```bash
caddy reload
```

### 3. Grafana Dashboard Panels

In the "Hermes Overview" dashboard, set panel iframe URLs:
- Panel 1 (Overview): `https://monitor.271224.xyz/dashboard/`
- Panel 2 (SPA): `https://hermes.271224.xyz/`
- Panel 3 (Hindsight): `https://monitor.271224.xyz/dashboard/hindsight`
- Panel 4 (Kanban): `https://monitor.271224.xyz/dashboard/kanban`

---

## Troubleshooting

### White Screen on Dashboard Pages

**Cause:** Browser caching old page version with absolute `/api/` paths.

**Fix:** Hard refresh (Ctrl+Shift+R). The current templates use relative `fetch('api/...')` paths.

### Grafana Panel Shows "Invalid Response"

**Cause:** Panel iframe URL points to a domain that no longer has a Caddy block (e.g. old `grafana.271224.xyz`).

**Fix:** Update all Grafana panel iframe URLs to use `monitor.271224.xyz` instead of `grafana.271224.xyz`, and `hermes.271224.xyz` for the SPA panel.

### Kanban Shows "No Data"

**Causes:**
1. Kanban service on CT 501 can't SSH to CT 301
2. Wrong SQLite query (using `archived_at IS NULL` instead of `status != 'archived'`)
3. Old uvicorn process with cached module

**Fix:**
```bash
# On CT 501
ssh root@10.10.20.31 "python3 -c 'import sqlite3; conn=sqlite3.connect(\"/root/.hermes/kanban.db\"); c=conn.cursor(); c.execute(\"SELECT name FROM sqlite_master WHERE type=\\\"table\\\"\"'); print(c.fetchall()); conn.close()'"

# Restart uvicorn
pkill -f "uvicorn.*main:app"
cd /opt/hermes-dashboard && python3 -m uvicorn main:app --host 0.0.0.0 --port 8080 &
```

### SPA Profiles Page 404

**Cause:** SPA was being served through Grafana domain, making absolute `/api/profiles` calls hit Grafana instead of CT 301.

**Fix:** Give SPA its own subdomain (`hermes.271224.xyz` → CT 301:9119 direct).

### FastAPI Catch-all Intercepts Specific Routes

**Cause:** `/api/{path:path}` registered before specific routes.

**Fix:** Move catch-all to be the LAST route in the file.
