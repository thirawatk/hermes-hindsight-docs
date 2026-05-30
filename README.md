# Hermes Agent — Hindsight Memory System

> **Complete operational documentation** for the Hindsight self-hosted memory backend powering Hermes Agent profiles.
>
> **Verified:** 2026-05-30 — All 6 banks retain/recall tested end-to-end. 5 gateways online. Hindsight API v0.7.1 healthy.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [System Components](#system-components)
- [Bank Registry](#bank-registry)
- [Configuration Reference](#configuration-reference)
- [Operations Runbook](#operations-runbook)
- [Audit Log](#audit-log)

---

## Overview

Hindsight is a **local, self-hosted memory system** that replaces paid cloud memory providers (Honcho). It gives each Hermes Agent profile its own isolated memory bank — persistent recall across sessions, automatic retention of key facts, and the ability to "reflect" on accumulated knowledge.

### Key Properties

| Property | Value |
|----------|-------|
| **API Version** | 0.7.1 |
| **API Mode** | `local_external` (self-hosted) |
| **Memory Mode** | `hybrid` (vector + structured graph) |
| **Recall Budget** | `mid` (balanced speed/coverage) |
| **Max Recall Tokens** | 4096 per query |
| **Auto Recall** | ✅ Enabled |
| **Auto Retain** | ✅ Enabled |
| **Retain Async** | ✅ Enabled |
| **LLM Provider** | OpenRouter (`openrouter/owl-alpha`) |
| **Embedding Provider** | Cohere |
| **Database** | PostgreSQL (local) |

### Why Hindsight

- **Zero cost** after initial setup — all data stays on your server
- **Per-profile isolation** — buddy memories never leak into trader banks, etc.
- **Multi-user support** — FA serves both Tae and Nhoo from one profile with separate banks via `bank_id_template`
- **Full control** — export, inspect, delete memories via REST API

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Proxmox LXC (Ubuntu)                     │
│                     IP: 10.10.20.31                             │
│                                                                 │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐        │
│  │   Gateway     │   │   Gateway     │   │   Gateway     │       │
│  │   (buddy)     │   │   (FA)        │   │   (investor)  │       │
│  │   PID 24669   │   │   PID 25440   │   │   PID 19853   │      │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘        │
│         │                  │                  │                  │
│  ┌──────┴───────┐   ┌──────┴───────┐   ┌──────┴───────┐        │
│  │   Gateway     │   │   Gateway     │   │              │        │
│  │   (trader)    │   │   (monitor)   │   │              │        │
│  │   PID 18989   │   │   PID 19029   │   │              │       │
│  └──────┬───────┘   └──────┬───────┘   └──────────────┘        │
│         │                  │                                    │
│         └──────────────────┼──────────────────┐                 │
│                            │                  │                 │
│  ┌─────────────────────────┴──────────────────┴──────────┐      │
│  │               Hindsight API v0.7.1                     │      │
│  │               PID 23500 (systemd)                      │      │
│  │               127.0.0.1:8888                           │      │
│  │                                                        │      │
│  │  ┌──────────────────────────────────────────────┐      │      │
│  │  │              PostgreSQL                       │      │      │
│  │  │  ┌─────────────────────────────────────┐     │      │      │
│  │  │  │ Bank: hermes-buddy-2135517501       │     │      │      │
│  │  │  │ Bank: hermes-financialanalyst-..    │     │      │      │
│  │  │  │ Bank: hermes-investor-2135517501    │     │      │      │
│  │  │  │ Bank: hermes-trader-2135517501      │     │      │      │
│  │  │  │ Bank: hermes-monitor-2135517501     │     │      │      │
│  │  │  └─────────────────────────────────────┘     │      │      │
│  │  └──────────────────────────────────────────────┘      │      │
│  └────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
1. Retain Flow (writing memories):
   Gateway → POST /v1/default/banks/{bank_id}/memories
           → Hindsight LLM extracts facts (observations, experiences, world)
           → Facts stored as nodes in knowledge graph
           → Links created (semantic, temporal, entity)
           → Async consolidation compacts similar facts

2. Recall Flow (reading memories):
   Gateway → POST /v1/default/banks/{bank_id}/memories/recall
           → Query embedding computed via Cohere
           → Vector search + graph traversal
           → Top results returned within max_tokens budget
           → Facts injected into LLM context window
```

---

## System Components

### Hindsight API Server

| Property | Value |
|----------|-------|
| **Process** | `hindsight-api --host 127.0.0.1 --port 8888` |
| **Service** | `hindsight-api.service` (systemd) |
| **PID** | 23500 |
| **Health** | `GET /health` → `{"status":"healthy","database":"connected"}` |
| **Docs** | `http://127.0.0.1:8888/docs` (Swagger UI) |
| **OpenAPI** | `http://127.0.0.1:8888/openapi.json` |

### Gateway Processes

| Profile | PID | CPU% | Memory% | Telegram Bot | Model |
|---------|-----|------|---------|--------------|-------|
| **buddy** | 24669 | 0.0 | 3.6 | 898221... | openrouter/owl-alpha |
| **financialanalyst** | 25440 | 0.0 | 2.7 | 889762... | google/gemma-4-31b-it:free |
| **investor** | 19853 | 0.0 | 2.2 | 892089... | google/gemma-4-31b-it:free |
| **trader** | 18989 | 0.0 | 2.3 | 866612... | google/gemma-4-31b-it:free |
| **monitor** | 19029 | 0.0 | 3.0 | 891450... | cohere/command-a-plus-05-2026 |

---

## Bank Registry

All active memory banks in the system:

| Bank ID | Profile | User | Nodes | Docs | Obs | Last Consolidated | Status |
|---------|---------|------|-------|------|-----|-------------------|--------|
| `hermes-buddy-2135517501` | buddy | Tae (2135517501) | 14 | 7 | 7 | 2026-05-30 02:14 | ✅ Active |
| `hermes-financialanalyst-2135517501` | financialanalyst | Tae (2135517501) | 5 | 8 | 2 | 2026-05-30 02:14 | ✅ Active |
| `hermes-financialanalyst-8748834444` | financialanalyst | Nhoo (8748834444) | 2 | 1 | 1 | 2026-05-30 02:15 | ✅ Ready |
| `hermes-investor-2135517501` | investor | Tae (2135517501) | 4 | 2 | 2 | 2026-05-30 02:15 | ✅ Active |
| `hermes-trader-2135517501` | trader | Tae (2135517501) | 4 | 3 | 2 | 2026-05-30 02:15 | ✅ Active |
| `hermes-monitor-2135517501` | monitor | Tae (2135517501) | 4 | 2 | 2 | 2026-05-30 02:15 | ✅ Active |

### Fact Types

Hindsight classifies memories into three types:

- **world** — General knowledge facts ("Tae is an infrastructure engineer in Thailand")
- **experience** — Events and actions ("Hindsight config audit completed on 2026-05-30")
- **observation** — Contextual notes ("FA profile uses gemma-4-31b-it:free model")

### Link Types

Relationships between facts are stored as:

- **semantic** — Facts with similar meaning
- **temporal** — Facts occurring near each other in time
- **entity** — Facts sharing the same named entities (people, places, tools)

---

## Configuration Reference

### Global Config

**File:** `~/.hermes/hindsight/config.json`

```json
{
  "mode": "local_external",
  "api_url": "http://127.0.0.1:8888",
  "api_key": "",
  "bank_id_template": "hermes-{profile}-{user}",
  "recall_budget": "mid",
  "recall_prefetch_method": "recall",
  "recall_max_tokens": 4096,
  "auto_recall": true,
  "auto_retain": true,
  "retain_async": true,
  "memory_mode": "hybrid"
}
```

### Per-Profile Config (config.yaml)

Each profile's `config.yaml` under `~/.hermes/profiles/<name>/config.yaml` contains a `memory:` section:

#### Single-User Profiles (buddy, investor, trader, monitor)

```yaml
memory:
  provider: hindsight
  memory_enabled: true
  memory_char_limit: 2200
  user_char_limit: 1375
  user_profile_enabled: true
  hindsight:
    api_url: http://127.0.0.1:8888
    bank_id: hermes-<profile>-2135517501
```

#### Multi-User Profile (financialanalyst)

```yaml
memory:
  provider: hindsight
  memory_enabled: true
  memory_char_limit: 2200
  user_char_limit: 1375
  user_profile_enabled: true
  flush_min_turns: 6
  nudge_interval: 10
  hindsight:
    api_url: http://127.0.0.1:8888
    bank_id_template: hermes-financialanalyst-{user}
```

The `{user}` variable is automatically resolved to the Telegram user ID at runtime:
- Tae (`2135517501`) → `hermes-financialanalyst-2135517501`
- Nhoo (`8748834444`) → `hermes-financialanalyst-8748834444`

### Per-Profile Environment (.env)

Each `~/.hermes/profiles/<name>/.env` must contain:

```bash
HINDSIGHT_MODE=local
HINDSIGHT_API_URL=http://127.0.0.1:8888
HINDSIGHT_BANK_ID=hermes-<profile>-<user_id>
HINDSIGHT_BUDGET=mid
```

> **NOTE:** `HINDSIGHT_API_KEY` in `.env` is a cosmetic placeholder. The local Hindsight API does not require authentication. The retain/recall operations work correctly without it.

### Configuration Completeness Checklist

When setting up a new profile, verify every item:

- [ ] `config.yaml` `memory.provider` = `hindsight`
- [ ] `config.yaml` `memory.memory_enabled` = `true`
- [ ] `config.yaml` `memory.hindsight.api_url` = `http://127.0.0.1:8888`
- [ ] `config.yaml` `memory.hindsight.bank_id` set (single user) OR `bank_id_template` set (multi user)
- [ ] `.env` has `HINDSIGHT_MODE=local`
- [ ] `.env` has `HINDSIGHT_API_URL=http://127.0.0.1:8888`
- [ ] `.env` has `HINDSIGHT_BANK_ID` matching config bank_id
- [ ] `.env` has `HINDSIGHT_BUDGET=mid`
- [ ] Gateway restarted after config changes: `hermes gateway restart --profile <name>`

---

## Operations Runbook

### Health Checks

```bash
# 1. Hindsight API health
curl http://127.0.0.1:8888/health
# Expected: {"status":"healthy","database":"connected"}

# 2. List all banks
curl http://127.0.0.1:8888/v1/default/banks | python3 -m json.tool

# 3. Check bank stats
curl http://127.0.0.1:8888/v1/default/banks/hermes-buddy-2135517501/stats | python3 -m json.tool

# 4. Verify gateway processes
ps aux | grep "hermes_cli.main" | grep gateway

# 5. Check systemd service
systemctl status hindsight-api.service
```

### Manual Retain (Write Memory)

```bash
curl -s -X POST \
  http://127.0.0.1:8888/v1/default/banks/hermes-buddy-2135517501/memories \
  -H "Content-Type: application/json" \
  -d '{
    "items": [{"content": "User prefers concise responses without emojis when discussing financial topics"}]
  }' | python3 -m json.tool
```

### Manual Recall (Search Memories)

```bash
curl -s -X POST \
  http://127.0.0.1:8888/v1/default/banks/hermes-buddy-2135517501/memories/recall \
  -H "Content-Type: application/json" \
  -d '{
    "query": "user communication preferences",
    "max_tokens": 500
  }' | python3 -m json.tool
```

### Create a New Bank

Banks are auto-created on first retain, but you can pre-create:

```bash
curl -s -X PUT \
  http://127.0.0.1:8888/v1/default/banks/hermes-newprofile-123456789 \
  -H "Content-Type: application/json" \
  -d '{"name": "New Profile (User)", "disposition": {"fact_types": ["world", "experience", "observation"]}}' \
  | python3 -m json.tool
```

### Delete a Bank (Destructive)

```bash
curl -s -X DELETE \
  http://127.0.0.1:8888/v1/default/banks/hermes-oldprofile-123456789
```

### Clear All Memories in a Bank (Keep Bank)

```bash
curl -s -X DELETE \
  http://127.0.0.1:8888/v1/default/banks/hermes-buddy-2135517501/memories
```

### Trigger Consolidation

Compacts similar facts to reduce token usage:

```bash
curl -s -X POST \
  http://127.0.0.1:8888/v1/default/banks/hermes-buddy-2135517501/consolidate
```

### Check Pending Operations

```bash
curl -s http://127.0.0.1:8888/v1/default/banks/hermes-buddy-2135517501/operations \
  | python3 -m json.tool
```

### Restart Procedures

```bash
# Restart Hindsight API
sudo systemctl restart hindsight-api.service

# Restart a specific gateway
hermes gateway restart --profile buddy

# Restart all gateways (one by one)
for p in buddy financialanalyst investor trader monitor; do
  hermes gateway restart --profile $p
done
```

---

## Audit Log

### 2026-05-30 — Full Configuration Audit & Cleanup

**Audit performed by:** OWL (buddy profile)  
**Scope:** All 5 profiles (buddy, financialanalyst, investor, trader, monitor)  
**Hindsight API version:** 0.7.1

#### Findings

| Area | Status | Notes |
|------|--------|-------|
| API Health | ✅ Healthy | `/health` returns connected |
| All Gateways Online | ✅ 5/5 | All PIDs alive |
| Retain/Recall E2E | ✅ All banks pass | Verified on 6 banks |
| Config Consistency | ✅ All profiles correct | Provider, URLs, bank IDs all present |
| Multi-User Isolation | ✅ Working | FA correctly uses `bank_id_template` |
| Stale Banks | ⚠️ Found and cleaned | See below |

#### Stale Banks Deleted

| Bank ID | Reason | Data at Deletion |
|---------|--------|------------------|
| `hermes-merger-2135517501` | Renamed to "financialanalyst" on 2026-05-29 | Empty (0 nodes) |
| `hermes-merger-8748834444` | Renamed to "financialanalyst" on 2026-05-29 | Empty (0 nodes) |
| `hermes-default-2135517501` | Honcho migration leftover | 257 nodes, 11 docs (data absorbed into profile banks) |
| `hermes-default` | Honcho migration leftover | 14 nodes, 1 doc |
| `test-bank` | Testing artifact | 0 nodes, 1 doc |

#### Verification Results (Post-Cleanup)

All 6 active banks passed retain → recall verification:

| Bank | Retain | Recall | Fact Types |
|------|--------|--------|------------|
| buddy | ✅ 203 tokens | ✅ 6 results | experience×6 |
| FA (Tae) | ✅ 253 tokens | ✅ 4 results | experience×3, observation×1 |
| FA (Nhoo) | ✅ 223 tokens | ✅ 1 result | experience×1 |
| investor | ✅ 180 tokens | ✅ 3 results | experience×2, observation×1 |
| trader | ✅ 218 tokens | ✅ 3 results | experience×2, observation×1 |
| monitor | ✅ 216 tokens | ✅ 3 results | experience×2, observation×1 |

#### Key Operational Notes

1. **`HINDSIGHT_API_KEY=***` in `.env` files is cosmetic** — The local API does not require authentication. Do not attempt to replace with a real key.

2. **Nhoo's FA bank (`hermes-financialanalyst-8748834444`) is empty but functional** — It was pre-created and will populate automatically when Nhoo starts chatting with the FA bot.

3. **All banks have `pending_operations=0` and `failed_operations=0`** — No stuck background tasks.

4. **Consolidation ran recently on all banks** (around 2026-05-30 02:14-02:15 UTC) — Facts are compacted and optimized.

5. **The global `bank_id_template` (`hermes-{profile}-{user}`) in `hindsight/config.json` serves as the default** — Individual profile configs override this with explicit `bank_id` or profile-specific templates.

---

*This document is maintained as part of the Hermes Agent operational runbook. Last updated: 2026-05-30.*
