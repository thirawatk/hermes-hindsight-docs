# Network Architecture — Complete Reference

> **Last verified:** 2026-05-31

---

## Table of Contents

- [LXC Inventory](#lxc-inventory)
- [Network Diagram](#network-diagram)
- [Domain Routing](#domain-routing)
- [Caddy Routing Details](#caddy-routing-details)
- [DNS Configuration](#dns-configuration)
- [Firewall Rules](#firewall-rules)
- [SSH Access Matrix](#ssh-access-matrix)
- [Data Flow Diagrams](#data-flow-diagrams)

---

## LXC Inventory

### Proxmox Node 1 (10.10.20.11)

| CT ID | Name | IP | VLAN | Role | Key Services |
|-------|------|----|------|------|--------------|
| **102** | dns | 10.10.20.22 | 20 | DNS server | Bind9, DoH |
| **103** | caddy | 10.10.20.23 | 20 | Reverse proxy | Caddy (HTTPS, auto-TLS) |
| **301** | hermes-ubuntu | 10.10.20.31 | — | Main agent host | Hermes Agent (5 gateways + default), Hindsight API, Kanban DB, Hermes SPA |
| **402** | paperless | 10.10.20.42 | — | Document management | Paperless-ngx |
| **403** | joplin | 10.10.20.43 | — | Note sync | Joplin Server |
| **404** | cwa | 10.10.20.44 | — | — | — |
| **501** | monitor | 10.10.20.51 | — | Monitoring | Grafana (3000), FastAPI Dashboard (8080) |

> **NOTE:** CT ID ≠ last octet of IP address. Always use the IP, not the ID, for SSH connections.

### Storage

| Pool | Size | Used | Mount (CT 301) | Purpose |
|------|------|------|----------------|---------|
| `rpool` | 20 GB | ~7.4 GB (37%) | `/` | OS, Hermes Agent, Hindsight API, gateway processes |
| `ssd-vault` | 923 GB | ~78 MB (1%) | `/mnt/hindsight` | Hindsight PostgreSQL data, vector indexes, all memory banks |

---

## Network Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Proxmox Host (node1)                            │
│                         IP: 10.10.20.11                                 │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      VLAN 20 (Management)                         │  │
│  │                                                                   │  │
│  │  CT 102 (DNS)        CT 103 (Caddy)                              │  │
│  │  10.10.20.22          10.10.20.23                                │  │
│  │  pw: (unknown)        pw: Th!2awatCD                             │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      Internal Network                              │  │
│  │                                                                   │  │
│  │  CT 301 (Hermes)     CT 404 (CWA)     CT 501 (Monitor)          │  │
│  │  10.10.20.31          10.10.20.44       10.10.20.51              │  │
│  │                                                                   │  │
│  │  CT 402 (Paperless)  CT 403 (Joplin)                             │  │
│  │  10.10.20.42          10.10.20.43                                │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
           │                                              │
           │         Cloudflare Tunnel                    │
           │    (*.271224.xyz CNAME)                      │
           ▼                                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           INTERNET                                       │
│                                                                          │
│  User Browser                                                            │
│     │                                                                    │
│     ├──► monitor.271224.xyz ──── Caddy (CT 103) ──┬──► CT 501:3000     │
│     │                                               │    (Grafana)       │
│     │                                               └──► CT 501:8080     │
│     │                                                    (/dashboard/*)  │
│     │                                                                    │
│     └──► hermes.271224.xyz ─── Caddy (CT 103) ────► CT 301:9119        │
│                              (direct, no proxy)     (Hermes SPA)        │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Domain Routing

### Public Domains (via Cloudflare Tunnel)

| Domain | Caddy Block | Destination | Purpose |
|--------|-------------|-------------|---------|
| `monitor.271224.xyz` | `/dashboard/*` → strip_prefix | CT 501:8080 | Dashboard pages (iframe in Grafana) |
| `monitor.271224.xyz` | `*` (fallback) | CT 501:3000 | Grafana web UI |
| `hermes.271224.xyz` | ALL traffic | CT 301:9119 | Hermes Dashboard SPA |
| `jump.271224.xyz` | ALL traffic | jump-ubuntu.lan | Jump host / web terminal |
| `pve1.271224.xyz` | ALL traffic | 10.10.20.11:8006 | Proxmox Web UI |
| `dns.271224.xyz` | ALL traffic | 10.10.20.22:53443 | DNS over HTTPS |
| `paperless.271224.xyz` | ALL traffic | paperless.lan:8000 | Paperless-ngx |
| `joplin.271224.xyz` | ALL traffic | joplin.lan:22300 | Joplin Server |
| `calibre.271224.xyz` | ALL traffic | calibre-web.lan:8083 | Calibre Web |
| `ap1.271224.xyz` | ALL traffic | 192.168.2.2 | Access Point 1 |
| `ap2.271224.xyz` | ALL traffic | 192.168.2.3 | Access Point 2 |
| `router.271224.xyz` | ALL traffic | Router self | Router config |
| `caddy.271224.xyz` | Response only | CT 103 | Health check ("Caddy Gateway is Online") |

### Retired Domains

| Domain | Reason |
|--------|--------|
| `grafana.271224.xyz` | Removed — consolidated to `monitor.271224.xyz` |

---

## Caddy Routing Details

### `monitor.271224.xyz` Block

```caddy
monitor.271224.xyz {
    import cloudflare_tls
    handle /dashboard/* {
        uri strip_prefix /dashboard
        reverse_proxy http://monitor.271224.xyz.lan:8080
    }
    reverse_proxy http://monitor.271224.xyz.lan:3000
}
```

**Routing logic:**
1. Request path starts with `/dashboard/` → strip prefix → forward to CT 501:8080
2. All other paths → forward to CT 501:3000 (Grafana)

**Example:**
- `monitor.271224.xyz/dashboard/kanban` → CT 501:8080 gets `/kanban` → FastAPI kanban page
- `monitor.271224.xyz/d/hermes-overview` → CT 501:3000 gets `/d/hermes-overview` → Grafana dashboard

### `hermes.271224.xyz` Block

```caddy
hermes.271224.xyz {
    import cloudflare_tls
    reverse_proxy http://10.10.20.31:9119
}
```

All traffic goes directly to CT 301:9119. No stripping, no path manipulation.

### Cloudflare TLS Snippet

```caddy
(cloudflare_tls) {
    tls {
        issuer acme {
            dns cloudflare {env.CLOUDFLARE_API_TOKEN}
            resolvers 1.1.1.1
        }
    }
}
```

Applied to all public domains. Uses DNS-01 challenge through Cloudflare API.

---

## DNS Configuration

### External (Cloudflare)

- **Wildcard CNAME:** `*.271224.xyz` → `cfargotunnel.com` (Cloudflare Tunnel)
- All subdomains automatically resolved via tunnel
- No individual A/AAAA records needed

### Internal (CT 102 — Bind9)

Internal DNS resolves `.271224.xyz.lan` hostnames:
- `monitor.271224.xyz.lan` → 10.10.20.51
- `paperless.271224.xyz.lan` → 10.10.20.42
- `joplin.271224.xyz.lan` → 10.10.20.43
- etc.

Caddy uses `.lan` variants for upstream connections (internal DNS resolution).

---

## Firewall Rules

### CT 103 (Caddy)

- **Port 80:** HTTP (for ACME HTTP-01 if needed)
- **Port 443:** HTTPS (main entry point)
- **Port 22:** SSH (restricted)

### CT 301 (Hermes)

- **Port 9119:** Hermes Dashboard SPA (internal, proxied through Caddy)
- **Port 8888:** Hindsight API (localhost only — not exposed)
- **Port 22:** SSH

### CT 501 (Monitor)

- **Port 3000:** Grafana (internal, proxied through Caddy)
- **Port 8080:** FastAPI Dashboard (internal, proxied through Caddy)
- **Port 22:** SSH

> **Key principle:** Only Caddy (CT 103) is directly reachable from the internet via Cloudflare Tunnel. All other services are internal and go through Caddy's reverse proxy.

---

## SSH Access Matrix

| From → To | User | Method | Purpose |
|-----------|------|--------|---------|
| Local workstation → CT 301 | root | SSH | Hermes management |
| Local workstation → CT 501 | root | SSH | Dashboard management |
| Local workstation → CT 103 | root | SSH | Caddy management |
| CT 501 → CT 301 | root | SSH (key-based) | Dashboard data queries |

**CT 501 → CT 301 SSH:** The dashboard backend on CT 501 connects to CT 301 via SSH (key-based, no password) to query:
- Gateway process status (`ps aux`)
- Storage usage (`df -h`)
- Hindsight API health (`curl 127.0.0.1:8888/health`)
- Kanban SQLite databases

---

## Data Flow Diagrams

### Dashboard Page Load (Kanban Example)

```
Browser
  │
  ├─ GET https://monitor.271224.xyz/dashboard/kanban
  │
  ▼
Caddy (CT 103:443)
  │ path matches /dashboard/*
  │ strip_prefix /dashboard
  │ forward to CT 501:8080 /kanban
  │
  ▼
FastAPI (CT 501:8080)
  │ render kanban.html template
  │ services.kanban.get_boards()
  │   │
  │   ├─ SSH to CT 301
  │   │   └─ python3 one-liner → query kanban.db
  │   │       └─ JSON results
  │   │
  │   └─ Return board list with counts
  │
  ▼
HTML Response (with embedded board names & counts)
  │
  ▼
Browser JS executes:
  │ fetch('api/kanban/tasks/default')
  │ resolves to: monitor.271224.xyz/dashboard/api/kanban/tasks/default
  │
  ▼
Caddy (CT 103)
  │ strip_prefix /dashboard
  │ forward to CT 501:8080 /api/kanban/tasks/default
  │
  ▼
FastAPI (CT 501:8080)
  │ specific route: GET /api/kanban/tasks/{board_slug}
  │ services.kanban.get_tasks("default")
  │   └─ SSH to CT 301 → query SQLite
  │
  ▼
JSON Response → Browser renders task table
```

### SPA Load (Hermes Dashboard)

```
Browser
  │
  ├─ GET https://hermes.271224.xyz/
  │
  ▼
Caddy (CT 103:443)
  │ ALL traffic → CT 301:9119
  │
  ▼
Hermes SPA (CT 301:9119)
  │ serves index.html (SPA shell)
  │
  ▼
Browser JS executes:
  │ fetch('/api/profiles')   ← ABSOLUTE path, correct for SPA domain
  │ fetch('/api/sessions')
  │
  ▼
Hermes SPA (CT 301:9119)
  │ /api/* routes on the SAME server
  │ returns gateway status, sessions, etc.
  │
  ▼
SPA renders data
```

> **Key difference:** The SPA uses ABSOLUTE paths (`/api/profiles`) because it runs on its own domain. The monitoring dashboard pages use RELATIVE paths (`api/kanban/boards`) because they're served behind a `strip_prefix` proxy.
