# Mistakes & Solutions — Complete Troubleshooting Log

> Every mistake made during the dashboard and kanban deployment, with root cause and fix.

---

## Table of Contents

- [Dashboard Architecture Mistakes](#dashboard-architecture-mistakes)
- [Caddy Routing Mistakes](#caddy-routing-mistakes)
- [Kanban Database Mistakes](#kanban-database-mistakes)
- [JavaScript/Frontend Mistakes](#javascriptfrontend-mistakes)
- [Grafana Integration Mistakes](#grafana-integration-mistakes)
- [SPA Integration Mistakes](#spa-integration-mistakes)
- [Template/Jinja2 Mistakes](#templatejinja2-mistakes)
- [General Proxmox/LXC Mistakes](#general-proxmoxlxc-mistakes)

---

## Dashboard Architecture Mistakes

### Mistake #1: SPA API calls hitting Grafana (absolute vs relative paths)

**What happened:** The SPA was hosted at `grafana.271224.xyz/dashboard/hermes-ui/`. Its JavaScript made API calls to absolute paths like `fetch('/api/profiles')`. Caddy routed `/api/profiles` to Grafana (port 3000), which returned 401. The Profiles page showed 404.

**Root cause:** SPA's absolute `/api/*` paths resolved to the server root (`grafana.271224.xyz/api/`) instead of the SPA path (`grafana.271224.xyz/dashboard/hermes-ui/api/`). Caddy sent this to Grafana which has no `/api/*` routes.

**Solution:** Give the SPA its own dedicated subdomain `hermes.271224.xyz` pointing directly to CT 301:9119 (Hermes' own dashboard server). No proxy, no path rewriting needed.

**Lesson:** Never serve an SPA with absolute API paths through a subpath proxy. Either give the SPA its own origin or rewrite the JS.

---

### Mistake #2: Dashboard pages using absolute API paths

**What happened:** Early versions of dashboard templates used `fetch('/api/gateway')` (absolute). When served through `monitor.271224.xyz/dashboard/*`, these resolved to `monitor.271224.xyz/api/grafana` → Caddy sent to Grafana → 401 → white screen.

**Root cause:** Same as above, but for the monitoring dashboard pages (not the SPA).

**Solution:** Changed all `fetch('/api/...')` to `fetch('api/...')` (relative) in all dashboard templates (overview.html, hindsight.html, kanban.html). Browser resolves relative paths from current URL path. So `monitor.271224.xyz/dashboard/` + `fetch('api/kanban')` = `monitor.271224.xyz/dashboard/api/kanban` → Caddy strips `/dashboard` → CT 501 gets `/api/kanban` → correct handler.

**Lesson:** Pages served behind `strip_prefix` proxies must use relative API paths.

---

### Mistake #3: Two domains when one was enough

**What happened:** Initially used both `monitor.271224.xyz` AND `grafana.271224.xyz` pointing to CT 501. Grafana panels referenced `grafana.271224.xyz`. User asked why two domains. Then removed `grafana.271224.xyz` Caddy block → Grafana panel iframes tried to load from dead domain → "invalid response" error.

**Root cause:** Premature proliferation of domains. All CT 501 services can route through one domain with path-based dispatch.

**Solution:**
1. Removed `grafana.271224.xyz` Caddy block
2. Updated all 4 Grafana panel iframe URLs to use `monitor.271224.xyz/dashboard/...`

**Lesson:** Minimize domains. Use path-based routing where possible. When retiring a domain, audit ALL references everywhere (including Grafana panel configs).

---

### Mistake #4: Kanban service not reading default board

**What happened:** The kanban service on CT 501 only scanned `/root/.hermes/kanban/boards/*/kanban.db` directories. The default board at `/root/.hermes/kanban.db` (outside `boards/`) was invisible. Default board showed 0 tasks.

**Root cause:** Code assumed all boards are in subdirectories. The default board has a special flat path.

**Solution:** Updated `kanban.py` to:
1. First check if `/root/.hermes/kanban.db` exists → add as "default" board
2. Then scan `boards/*/kanban.db` for additional boards

**Lesson:** Special-case the default board. It's not in the boards directory.

---

## Caddy Routing Mistakes

### Mistake #5: catch-all before `handle /dashboard/*`

**What happened:** Initially tried using a catch-all reverse proxy on `monitor.271224.xyz` → CT 501:3000, with a separate config file for dashboard routes. Caddy merged configs unpredictably.

**Root cause:** Using `import` with separate config files can cause route ordering issues.

**Solution:** Used a single `handle` block inside the `monitor.271224.xyz` site block:
```caddy
handle /dashboard/* {
    uri strip_prefix /dashboard
    reverse_proxy http://monitor.271224.xyz.lan:8080
}
reverse_proxy http://monitor.271224.xyz.lan:3000
```
The `handle` block takes priority, everything else falls through to the generic reverse_proxy.

**Lesson:** Use `handle` for path-based routing within a single site block. Don't split across files.

---

### Mistake #6: FastAPI catch-all route intercepting specific routes

**What happened:** The catch-all `@app.get("/api/{path:path}")` was registered BEFORE specific routes like `/api/gateway`, `/api/hindsight/health`, etc. Every API request hit the catch-all and returned 404.

**Root cause:** Python decorators are evaluated in order of definition. In FastAPI, route registration order matters.

**Solution:** Moved the catch-all to be the LAST route defined in `main.py`. Specific routes must always be defined first.

```python
# CORRECT ORDER:
@app.get("/api/gateway")          # Specific first
async def api_gateway(): ...

@app.get("/api/storage")          # Specific
async def api_storage(): ...

# ... more specific routes ...

@app.get("/api/{path:path}")      # Catch-all LAST
async def api_not_found(path: str): ...
```

**Lesson:** In FastAPI, always register catch-all routes LAST.

---

## Kanban Database Mistakes

### Mistake #7: Using `archived_at IS NULL` filter

**What happened:** Kanban service queries used `WHERE archived_at IS NULL` to filter active tasks. No results returned despite tasks existing.

**Root cause:** The `tasks` table has NO `archived_at` column. The column doesn't exist in the schema. SQLite doesn't error on WHERE with missing column in some contexts — it just returns unexpected results.

**Solution:** Changed all queries to use `WHERE status != 'archived'` instead.

```python
# WRONG:
"SELECT * FROM tasks WHERE archived_at IS NULL"

# CORRECT:
"SELECT * FROM tasks WHERE status != 'archived'"
```

**Lesson:** Always verify the actual schema before writing queries. Don't assume column names.

---

### Mistake #8: Per-profile kanban boards (buddy-investor, buddy-trader, buddy-fa)

**What happened:** Created separate kanban boards for each profile pair (buddy-investor, buddy-trader, buddy-fa) thinking each worker needs its own board. All remained empty because cross-profile dispatch uses the `assignee` field on a shared board.

**Root cause:** Misunderstood the dispatch architecture. The dispatcher scans ALL boards for tasks with matching assignees, but a single shared board is simpler and works identically.

**Solution:**
1. Deleted empty boards: `buddy-investor`, `buddy-trader`, `buddy-fa`
2. Kept only `buddy-monitor` (for buddy↔monitor orchestration) and `default` (for all other tasks)
3. All cross-profile tasks go to the `default` board with `assignee` set to target profile

**Lesson:** Don't create infrastructure for hypothetical needs. Start with shared boards, split only when there's an actual reason.

---

### Mistake #9: Typo in SQL — bare `BY created_at DESC`

**What happened:** Query had `"SELECT * FROM tasks WHERE archived_at IS NULL BY created_at DESC"` — missing `ORDER` keyword.

**Root cause:** Typo during editing. Python f-string or string concatenation dropped the `ORDER` keyword.

**Solution:** Fixed to `"SELECT * FROM tasks WHERE status != 'archived' ORDER BY created_at DESC"`

**Lesson:** Always validate SQL before deploying. A missing keyword can silently produce wrong results (unordered instead of error in some cases).

---

## JavaScript/Frontend Mistakes

### Mistake #10: Jinja2 dumping dict object in template

**What happened:** Template used `{{ health }}` which rendered as Python dict repr `{'status': 'healthy', 'database': 'connected'}` — a huge blob of text instead of a clean status badge.

**Root cause:** Jinja2 `{{ variable }}` on a dict renders the full Python repr.

**Solution:** Access specific fields:
```html
<!-- WRONG: -->
{{ health }}

<!-- CORRECT: -->
{{ health.status }}  → "healthy"
{{ health.database }} → "connected"
```

Applied same fix for `version.api_version` (not `version`), `bank.name` (not `bank`), etc.

**Lesson:** Jinja2 templates must always access object fields, never dump raw dicts/objects.

---

### Mistake #11: Browser caching old JavaScript with absolute paths

**What happened:** After fixing templates to use relative paths, users still saw white screens. The browser served cached JS with old absolute `/api/` paths.

**Root cause:** Browser cache. The HTML had `Cache-Control` headers or the browser aggressively cached the previous version.

**Solution:**
- Hard refresh: Ctrl+Shift+R (bypasses cache)
- Long-term: Add cache-busting query params (`app.js?v=20260531`) or set `Cache-Control: no-cache`

**Lesson:** After deploying frontend changes, always test with hard refresh. Also set Jinja2 `cache_size=0` during development.

---

## Grafana Integration Mistakes

### Mistake #12: Grafana dashboard panels still pointing to retired domain

**What happened:** After removing `grafana.271224.xyz` Caddy block, the Grafana "Hermes Overview" dashboard panels still referenced the old domain. Users saw "grafana.271224.xyz sent an invalid response."

**Root cause:** Updating Caddy doesn't auto-update Grafana panel configs. Panel iframe URLs are stored in Grafana's JSON dashboard definition.

**Solution:** Updated all panel Grafana dashboard JSON through Grafana UI → Dashboard settings → JSON Model. Changed all iframe src from `https://grafana.271224.xyz/dashboard/...` to `https://monitor.271224.xyz/dashboard/...`.

**Lesson:** When retiring a domain, grep EVERYTHING — Caddy, templates, Grafana JSON, browser bookmarks, docs.

---

### Mistake #13: Grafana panel Content Security Policy

**What happened:** Grafana panels showed blank content initially despite correct iframe URLs.

**Root cause:** Grafana's default CSP blocks iframe embedding from same origin.

**Solution:** Set in Grafana config:
```ini
[security]
allow_embedding = true

[panels]
disable_sanitize_html = true
```

**Lesson:** Grafana embeds require explicit security relaxation.

---

## SPA Integration Mistakes

### Mistake #14: Serving SPA through CT 501 proxy

**What happened:** Initially tried to proxy SPA traffic through CT 501's FastAPI (`/hermes-ui/*` → CT 301:9119). Required complex path rewriting, SPA asset rewriting, and still had issues with absolute API paths in JS.

**Root cause:** SPA expects to run at `/`. Proxying with path rewriting breaks assumptions about static assets, API paths, and WebSocket connections.

**Solution:** Removed all SPA proxy code from CT 501. Created dedicated `hermes.271224.xyz` Caddy block → CT 301:9119 directly. SPA runs natively on its own origin.

**Lesson:** SPAs should run on their own origin. Don't proxy them through another app's path.

---

## Template/Jinja2 Mistakes

### Mistake #15: Jinja2 `{{ dict }}` dumps Python repr

**What happened:** (Same as #10 but worth repeating) `{{ hindsight }}` rendered as full Python dict.

**Root cause:** Jinja2 default string conversion for dict objects.

**Solution:** Always access specific fields: `{{ hindsight.status }}` not `{{ hindsight }}`.

---

### Mistake #16: Jinja2 TypeError with dict context

**What happened:** `TypeError: unhashable type: 'dict'` when using Starlette's `Jinja2Templates`.

**Root cause:** Jinja2 3.1 + Starlette have a cache bug where passing a dict context causes hash errors.

**Solution:** Use raw `jinja2.Environment(cache_size=0)` instead of `starlette.templating.Jinja2Templates`:
```python
_templates_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader("/opt/hermes-dashboard/templates"),
    cache_size=0,
    auto_reload=True,
)
```

**Lesson:** When using Jinja2 with FastAPI/Starlette, avoid `Jinja2Templates` if you encounter dict hashing errors. Use raw `jinja2.Environment`.

---

## General Proxmox/LXC Mistakes

### Mistake #17: Confusing CT ID with IP address

**What happened:** Tried SSH to CT at `10.10.20.501` thinking CT ID 501 = last octet .501.

**Root cause:** CT ID ≠ IP last octet. CT 501 has IP 10.10.20.51, CT 103 has IP 10.10.20.23.

**Solution:** Always use the documented IP addresses, never assume CT ID maps to IP.

---

### Mistake #18: SSH heredocs corrupting nested quotes

**What happened:** Complex Python scripts with quotes inside quotes inside quotes broke when passed through SSH heredocs (`ssh host << 'EOF'`).

**Root cause:** Nested quote escaping in bash is fragile and error-prone.

**Solution:** Use base64 encoding:
```python
import base64
script = "import sqlite3; conn=sqlite3.connect('...')"
encoded = base64.b64encode(script.encode()).decode()
ssh_cmd = f"echo '{encoded}' | base64 -d | python3"
```

**Lesson:** For complex scripts over SSH, always use base64 encoding. Never try to escape nested quotes manually.

---

### Mistake #19: Old uvicorn process with cached Python module

**What happened:** After updating `services/kanban.py`, the changes weren't reflected. The dashboard still showed old behavior.

**Root cause:** The uvicorn worker process had cached the old Python module in memory. Simply replacing the file doesn't reload it.

**Solution:** Kill and restart uvicorn:
```bash
pkill -f "uvicorn.*main:app"
cd /opt/hermes-dashboard && python3 -m uvicorn main:app --host 0.0.0.0 --port 8080 &
```

Or use `--reload` flag during development:
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8080
```

**Lesson:** Always restart the server after changing Python source files. Don't assume auto-reload is on.

---

### Mistake #20: Not using `strip_prefix` with Caddy handle blocks

**What happened:** Initial dashboard config forwarded `/dashboard/kanban` to CT 501:8080 as `/dashboard/kanban`. FastAPI had no `/dashboard` route → 404.

**Root cause:** Missing `uri strip_prefix /dashboard` directive.

**Solution:**
```caddy
handle /dashboard/* {
    uri strip_prefix /dashboard
    reverse_proxy http://monitor.271224.xyz.lan:8080
}
```

**Lesson:** When proxying a subpath to an app that doesn't know about that subpath, always use `uri strip_prefix`.

---

## Summary of Key Lessons

1. **SPAs get their own domain** — don't proxy them through subpaths
2. **Relative API paths** for pages behind strip_prefix proxies
3. **Catch-all routes go LAST** in FastAPI
4. **`status != 'archived'`** not `archived_at IS NULL` (no such column)
5. **Default board is flat** at `/root/.hermes/kanban.db`, not in `boards/`
6. **Jinja2: access fields** not `{{ dict }}`
7. **Restart uvicorn** after code changes
8. **Hard refresh** browser after frontend changes
9. **Base64-encode** complex scripts for SSH
10. **Audit ALL references** when retiring a domain
11. **CT ID ≠ IP last octet**
12. **Grafana embeds need** `allow_embedding` and `disable_sanitize_html`

---

## Systemd Dual-Scope Mistakes

### Mistake #9: Installing gateway services in both system and user scope

**What happened:** 5 profile gateways (buddy, financialanalyst, investor, monitor, trader) had systemd service files in BOTH `/etc/systemd/system/` (system-level) AND `~/.config/systemd/user/` (user-level). Both used `--replace` flag + `Restart=always`.

**Root cause:** The `hermes gateway service install` command was run without specifying scope, and at some point system-level services were also installed (possibly via `hermes doctor --fix` or manual installation). The `--replace` flag in ExecStart kills any existing instance before starting. System-level and user-level services kept killing each other in an infinite loop.

**Impact:** 47+ restart cycles per profile, each consuming ~72MB RAM and ~3.7s CPU. Total resource waste: ~350MB RAM cycling, continuous process spawning.

**Solution:** Removed the 5 system-level unit files, kept user-level services. Disabled and cleaned up.

**Lesson:** NEVER install the same gateway service in both systemd scopes. User-level (`~/.config/systemd/user/`) is recommended for agent gateways. System-level (`/etc/systemd/system/`) should only be used for services that must run without any user login.

---

## Model Configuration Mistakes

### Mistake #10: Commented-out API keys in profile .env files

**What happened:** Model picker showed OpenCode Go and HuggingFace providers with 0 models for 6 of 8 profiles. The API keys were either commented out (# prefix) or completely missing from profile `.env` files.

**Root cause:** When profiles were created, their `.env` files were copied from a template that had the keys commented out. The gateway's `load_hermes_dotenv()` loads from the profile's own `.env` + project `.env`, NOT from the user's main `~/.hermes/.env`. Each profile must have all keys explicitly present and uncommented.

**Impact:** 6 profiles could not use OpenCode Go or HuggingFace models in the picker.

**Solution:** Uncommented keys in 4 profiles, added missing keys to 2 profiles, restarted gateways.

**Lesson:** When creating a new profile, always copy the FULL `.env` from default and verify all provider keys are active (not commented). Run: `grep -E "^[A-Z].*KEY=" /root/.hermes/profiles/{profile}/.env` to verify.
