# Hindsight Memory System — Architecture Deep Dive

## What is Hindsight?

Hindsight is a self-hosted, LLM-powered memory system designed for AI agents. It transforms unstructured conversation history into a structured knowledge graph that persists across sessions and can be semantically recalled on demand.

## Core Concepts

### Memory Banks

A **bank** is an isolated knowledge store. Each profile+user combination has its own bank. Banks are completely isolated — buddy memories are never visible to trader, and Tae's FA memories never leak into Nhoo's.

### Fact Types

Hindsight classifies retained information into three types:

| Type | Description | Example |
|------|-------------|---------|
| **world** | General knowledge and static facts | "Tae is an infrastructure engineer with 15+ years experience" |
| **experience** | Events, actions, and temporal facts | "Hindsight audit completed on 2026-05-30" |
| **observation** | Contextual notes and derived insights | "FA profile uses OpenRouter with gemma-4-31b-it:free" |

### Link Types

Facts are connected via three link types forming a knowledge graph:

| Link Type | Meaning | Example |
|-----------|---------|---------|
| **semantic** | Similar meaning | "User likes concise answers" ↔ "No fluff in responses" |
| **temporal** | Close in time | Two facts from the same conversation turn |
| **entity** | Shared entities | Two facts about the same person/tool/project |

### Memory Modes

| Mode | Behavior |
|------|----------|
| **hybrid** (current) | Vector semantic search + graph traversal + structured facts |
| **flat** | Simple vector search only, no graph relationships |

### Recall Budgets

Controls how many tokens are recalled per query:

| Budget | Behavior |
|--------|----------|
| `low` | Fast, surface-level recall. ~1000 tokens. |
| `mid` (current) | Balanced. ~2000 tokens. Good default. |
| `high` | Deep, thorough recall. ~4000 tokens. Slower but more comprehensive. |

### Auto-Recall vs Manual Recall

- **auto_recall** (enabled): Before each LLM call, Hindsight automatically searches the bank for relevant context and injects it into the system prompt.
- **manual recall**: The agent can explicitly search memory using the `memory` tool or direct API calls.

### Auto-Retain vs Manual Retain

- **auto_retain** (enabled): After each conversation turn, Hindsight's LLM analyzes the dialogue and automatically extracts and stores important facts.
- **manual retain**: Explicitly save a fact via `POST /memories` endpoint.

### Retain Async

When `retain_async: true`, memory writes happen in the background without blocking the agent's response. This prevents latency spikes during heavy conversation turns.

### Consolidation

A background process that merges similar facts to reduce redundancy and token consumption. Each bank tracks `last_consolidated_at` and `pending_consolidation`.

## API Surface

The Hindsight API (v0.7.1) exposes these core endpoints:

### Monitoring
- `GET /health` — API + database health
- `GET /metrics` — Prometheus metrics
- `GET /version` — API version and feature flags

### Bank Management
- `GET /v1/default/banks` — List all banks
- `PUT /v1/default/banks/{bank_id}` — Create/update bank
- `DELETE /v1/default/banks/{bank_id}` — Delete bank (destructive)
- `GET /v1/default/banks/{bank_id}/stats` — Node/doc/link counts
- `GET /v1/default/banks/{bank_id}/config` — Get bank configuration
- `PATCH /v1/default/banks/{bank_id}/config` — Update bank overrides

### Memory Operations
- `POST /v1/default/banks/{bank_id}/memories` — Retain (write) memories
- `POST /v1/default/banks/{bank_id}/memories/recall` — Recall (search) memories
- `GET /v1/default/banks/{bank_id}/memories/list` — List all memory units
- `DELETE /v1/default/banks/{bank_id}/memories` — Clear all memories in bank
- `GET /v1/default/banks/{bank_id}/memories/{memory_id}` — Get specific memory

### Graph & Entities
- `GET /v1/default/banks/{bank_id}/entities` — List entities
- `GET /v1/default/banks/{bank_id}/entities/graph` — Entity co-occurrence graph
- `GET /v1/default/banks/{bank_id}/graph` — Full memory graph

### Maintenance
- `POST /v1/default/banks/{bank_id}/consolidate` — Trigger consolidation
- `GET /v1/default/banks/{bank_id}/operations` — List async operations
- `POST /v1/default/banks/{bank_id}/operations/{op_id}/retry` — Retry failed operation

## Integration with Hermes Agent

### How Hermes Uses Hindsight

1. **Session Start**: Hermes loads the profile's config, discovers the `bank_id` or resolves `bank_id_template` from the user's Telegram ID.

2. **Pre-Recall** (auto): Before each LLM call, Hindsight queries the bank with the conversation context. Relevent facts are injected into the system prompt.

3. **Response Generation**: The LLM generates a response with the benefit of recalled memories.

4. **Post-Retain** (auto): Hindsight's LLM analyzes the conversation turn and extracts facts (observations, experiences, world knowledge). These are stored asynchronously if `retain_async: true`.

5. **Consolidation**: Background process periodically merges similar facts.

### Bank ID Resolution

```
bank_id = config.memory.hindsight.bank_id                          # static (single user)
       OR config.memory.hindsight.bank_id_template.format(...)     # dynamic (multi user)
```

For `bank_id_template: hermes-financialanalyst-{user}`:
- `{user}` is set to `event.from_user.id` (Telegram user ID)
- Result: `hermes-financialanalyst-2135517501` or `hermes-financialanalyst-8748834444`

### Profile Configuration Structure

```
~/.hermes/profiles/<name>/
├── config.yaml       # Main profile config (memory section)
├── .env              # API keys + Hindsight env vars
├── SOUL.md           # Agent personality
├── skills/           # Profile-specific skills
├── memories/         # Memory tool storage (MEMORY.md, USER.md)
└── sessions/         # Session transcripts
```

### Config.yaml Memory Section

```yaml
memory:
  provider: hindsight          # Must be exactly "hindsight"
  memory_enabled: true         # Must be true
  memory_char_limit: 2200      # Max chars for memory injection
  user_char_limit: 1375        # Max chars for user profile injection
  user_profile_enabled: true   # Include user profile in context
  flush_min_turns: 6           # Min turns before forced memory flush
  nudge_interval: 10           # Reminder interval for memory nudge
  hindsight:
    api_url: http://127.0.0.1:8888
    bank_id: hermes-<profile>-<user_id>           # Single user
    # OR
    bank_id_template: hermes-<profile>-{user}     # Multi user
```

### .env Hindsight Variables

```bash
HINDSIGHT_MODE=local                    # local | cloud
HINDSIGHT_API_URL=http://127.0.0.1:8888
HINDSIGHT_BANK_ID=hermes-<profile>-<user_id>
HINDSIGHT_BUDGET=mid                    # low | mid | high
# HINDSIGHT_API_KEY is cosmetic for local mode (not validated)
```

## Storage Layout

| ZFS Pool | Size | Used | Mount | Purpose |
|----------|------|------|-------|---------|
| `rpool` | 20 GB | 7.4 GB (37%) | `/` | OS, Hermes Agent, gateway processes, Hindsight API, LXC rootfs |
| `ssd-vault` | 923 GB | 78 MB (1%) | `/mnt/hindsight` | Hindsight PostgreSQL data + vector indexes + all memory banks |

Both pools are ZFS datasets on the Proxmox host. The Hindsight API binary runs on `rpool` (OS disk) while all persistent database files and vector indexes live on `ssd-vault` (dedicated SSD). `ssd-vault` is mounted into the LXC at `/mnt/hindsight` via a bind-mount or ZFS dataset passthrough.

## File Paths Reference

| File | Path |
|------|------|
| Hindsight API config | `~/.hermes/hindsight/config.json` |
| Hindsight API binary | `/usr/local/lib/hermes-agent/venv/bin/hindsight-api` |
| Hindsight systemd service | `/etc/systemd/system/hindsight-api.service` |
| Profile config | `~/.hermes/profiles/<name>/config.yaml` |
| Profile env | `~/.hermes/profiles/<name>/.env` |
| Gateway PID file | `~/.hermes/profiles/<name>/gateway.pid` |
| Gateway lock file | `~/.hermes/profiles/<name>/gateway.lock` |
| Session transcripts | `~/.hermes/profiles/<name>/sessions/` |
| Memory tool files | `~/.hermes/profiles/<name>/memories/` |

## Migration History

### Honcho → Hindsight (2026-05-29)

The system migrated from Honcho (paid cloud memory) to Hindsight (self-hosted local):

1. Hindsight API installed and configured with PostgreSQL
2. Profile configs updated: `provider: honcho` → `provider: hindsight`
3. `.env` files updated with Hindsight-specific variables
4. Per-profile banks created with naming convention `hermes-<profile>-<user_id>`
5. FA profile configured with `bank_id_template` for multi-user support
6. Nhoo's bank (`hermes-financialanalyst-8748834444`) pre-created empty

### Merger → Financialanalyst Rename (2026-05-29)

The "merger" profile was renamed to "financialanalyst":
- Profile directory: `~/.hermes/profiles/merger` → `~/.hermes/profiles/financialanalyst`
- Old banks `hermes-merger-*` were orphaned and later deleted empty
- Telegram bot token and config transferred to new profile name
