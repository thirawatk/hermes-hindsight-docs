# 2026-06-10 — Systemd Dual-Scope Conflict & Model Selection Fix

## Date: 2026-06-10
## Author: Hermes Agent (default profile)
## Severity: HIGH — gateway crash-loop consuming resources, model picker broken

---

## Issue 1: Gateway Crash-Loop (Dual-Scope Systemd Conflict)

### Symptoms
- 5 profile gateways (buddy, financialanalyst, investor, monitor, trader) in infinite crash-loop
- Restart counter reached 47-48 cycles
- Each cycle: start → 15s → SIGTERM → 10s → SIGKILL → 5min backoff → repeat
- Default gateway (hermes-gateway.service) unaffected

### Root Cause
Duplicate systemd service files existed in BOTH scopes:
- **System-level:** `/etc/systemd/system/hermes-gateway-{profile}.service` (WantedBy=multi-user.target)
- **User-level:** `/root/.config/systemd/user/hermes-gateway-{profile}.service` (WantedBy=default.target)

Both used `--replace` flag + `Restart=always`. The `--replace` flag kills any existing instance of the same profile before starting. When system-level started, it killed user-level. User-level restarted, killed system-level. Infinite mutual kill loop.

### Evidence
```
# System-level (winning, managed by PID 1)
systemctl status hermes-gateway-buddy.service
→ Active: active (running)

# User-level (crash-looping, managed by PID 316)
systemctl --user status hermes-gateway-buddy.service
→ Active: activating (auto-restart) — restart counter at 47

# Journal shows SIGTERM from both PIDs
signal=SIGTERM parent_pid=1 parent_name=systemd      # system-level killing
signal=SIGTERM parent_pid=316 parent_name=systemd    # user-level killing
```

### Fix
```bash
# 1. Stop and disable the 5 conflicting system-level services
for svc in buddy financialanalyst investor monitor trader; do
  systemctl stop hermes-gateway-${svc}.service
  systemctl disable hermes-gateway-${svc}.service
  rm -f /etc/systemd/system/hermes-gateway-${svc}.service
done

# 2. Daemon-reload
systemctl daemon-reload

# 3. Restart user-level services
systemctl --user daemon-reload
for svc in buddy financialanalyst investor monitor trader; do
  systemctl --user restart hermes-gateway-${svc}.service
done
```

### What Was NOT Touched
- `hermes-dashboard-ui.service` (system-level, separate service)
- `hermes-gateway-astrology.service` (system-level only, no user-level conflict)
- `hermes-gateway-midwife-consultant.service` (system-level only, no user-level conflict)
- `hermes-gateway.service` (default profile, user-level only, was fine)

### Prevention
When installing gateway services, NEVER install in both scopes. Choose one:
- **User-level** (recommended): `~/.config/systemd/user/` with `WantedBy=default.target`
- **System-level** (only for services that must run without user login): `/etc/systemd/system/` with `WantedBy=multi-user.target`

---

## Issue 2: Model Picker Showing 0 Models (OpenCode Go / HuggingFace)

### Symptoms
- Model picker showed OpenCode Go and HuggingFace providers but with 0 models
- Affected: astrology, financialanalyst, investor, midwife-consultant, monitor, trader
- Default and buddy were fine

### Root Cause
API keys `OPENCODE_GO_API_KEY` and `HF_TOKEN` were either:
1. **Commented out** (prefixed with `#`) in profile `.env` files (astrology, financialanalyst, investor, trader)
2. **Completely missing** from profile `.env` files (midwife-consultant, monitor)

The gateway loads env vars via `load_hermes_dotenv()` which reads from the **profile's own `.env`** + project `.env`, NOT from the user's main `~/.hermes/.env`. Each profile's `.env` must have all keys explicitly present and uncommented.

### Evidence
```bash
# Investigator profile .env — keys commented out
grep -E "OPENCODE_GO|HF_TOKEN" /root/.hermes/profiles/investor/.env
→ # OPENCODE_GO_API_KEY=***    (commented out!)
→ # HF_TOKEN=***               (commented out!)

# Buddy profile .env — keys active
grep -E "OPENCODE_GO|HF_TOKEN" /root/.hermes/profiles/buddy/.env
→ OPENCODE_GO_API_KEY=***     (active)
→ HF_TOKEN=***                (active)
```

### Fix
```bash
# Get keys from main .env
OPENCODE_KEY=$(grep "^OPENCODE_GO_API_KEY=" /root/.hermes/.env | cut -d= -f2-)
HF_TOK=$(grep "^HF_TOKEN=" /root/.hermes/.env | cut -d= -f2-)

# Uncomment in profiles that have them commented
for profile in astrology financialanalyst investor trader; do
  envfile="/root/.hermes/profiles/$profile/.env"
  sed -i "s/^# OPENCODE_GO_API_KEY=.*/OPENCODE_GO_API_KEY=$OPENCODE_KEY/" "$envfile"
  sed -i "s/^# HF_TOKEN=.*/HF_TOKEN=$HF_TOK/" "$envfile"
done

# Add to profiles that are missing them entirely
for profile in midwife-consultant monitor; do
  envfile="/root/.hermes/profiles/$profile/.env"
  echo "OPENCODE_GO_API_KEY=$OPENCODE_KEY" >> "$envfile"
  echo "HF_TOKEN=$HF_TOK" >> "$envfile"
done

# Restart affected gateways
for svc in astrology financialanalyst investor midwife-consultant monitor trader; do
  systemctl --user restart hermes-gateway-${svc}.service
done
```

### Prevention
When creating a new profile:
1. Copy the FULL `.env` from default: `cp /root/.hermes/.env /root/.hermes/profiles/{new-profile}/.env`
2. Verify all provider keys are active (not commented): `grep -E "^[A-Z].*KEY=" /root/.hermes/profiles/{new-profile}/.env`
3. Gateway's `load_hermes_dotenv()` does NOT auto-inherit from main `.env`

---

## Related: Hindsight Service

The `hindsight-api.service` was installed but disabled. It was enabled and started:
```bash
systemctl enable hindsight-api.service
systemctl start hindsight-api.service
```

All 8 profile banks verified accessible with 1,469 total facts across 12 banks.
