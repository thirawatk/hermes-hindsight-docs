# Kanban System — Multi-Profile Task Orchestration

> **Verified:** 2026-05-31 — Cross-profile dispatch working for all 4 worker profiles.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Boards](#boards)
- [Cross-Profile Dispatch](#cross-profile-dispatch)
- [Database Schema](#database-schema)
- [CLI Reference](#cli-reference)
- [Dashboard Integration](#dashboard-integration)
- [Workflow Examples](#workflow-examples)

---

## Overview

The Hermes Kanban system provides task orchestration across multiple agent profiles. Tasks are stored in SQLite databases on CT 301 and executed by the gateway process of the assigned profile.

### Key Properties

| Property | Value |
|----------|-------|
| **Storage** | SQLite on CT 301 (`10.10.20.31`) |
| **Task Dispatch** | Gateway-embedded dispatcher (60s tick) |
| **Claim Mechanism** | Atomic SQLite UPDATE with `claim_lock` + `claim_expires` |
| **Max Concurrent Dispatches** | 1 per gateway (serialized) |
| **Default Tick Interval** | 60 seconds |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         CT 301 (Ubuntu)                          │
│                                                                  │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐         │
│  │   Gateway     │   │   Gateway     │   │   Gateway     │        │
│  │   (buddy)     │   │   (investor)  │   │   (trader)    │        │
│  │   :dispatcher │   │   :dispatcher │   │   :dispatcher │        │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘         │
│         │                  │                  │                   │
│  ┌──────┴───────┐   ┌──────┴───────┐   ┌──────┴───────┐         │
│  │   Gateway     │   │   Gateway     │   │              │         │
│  │   (monitor)   │   │   (FA)        │   │              │         │
│  │   :dispatcher │   │   :dispatcher │   │              │        │
│  └──────┬───────┘   └──────┬───────┘   └──────────────┘         │
│         │                  │                                     │
│         └──────────────────┼──────────────────┐                  │
│                            │                  │                  │
│  ┌─────────────────────────┴──────────────────┴──────────┐       │
│  │                   SQLite Databases                     │       │
│  │                                                        │      │
│  │  /root/.hermes/kanban.db                               │      │
│  │    └── Board: "Financial Services" (slug: "default")   │      │
│  │                                                        │      │
│  │  /root/.hermes/kanban/boards/buddy-monitor/kanban.db   │      │
│  │    └── Board: "Monitor Services"                       │      │
│  └────────────────────────────────────────────────────────┘       │
└──────────────────────────────────────────────────────────────────┘
```

### Dispatch Flow

```
1. Orchestrator (buddy) creates task:
   hermes kanban create "Task title" --assignee monitor

2. Task is INSERTed into SQLite with status='ready'

3. Monitor's gateway dispatcher ticks (every 60s):
   - SELECT * FROM tasks WHERE status='ready' AND assignee='monitor'
   - AND (claim_lock IS NULL OR claim_expires < now)
   - Atomic UPDATE: claim_lock=<uuid>, claim_expires=now+300

4. If claim succeeds:
   - Spawn: hermes -p monitor run --kanban <task_id>
   - Worker processes task, updates status to 'running' then 'done'

5. If claim fails (another gateway claimed it first):
   - Skip, wait for next tick
```

### Why Atomic Claim?

Multiple gateways can scan the same board. The atomic `UPDATE ... WHERE claim_lock IS NULL` ensures only one gateway picks up a task, even if 5 gateways scan simultaneously.

---

## Boards

### Active Boards

| Slug | Display Name | DB Location | Description |
|------|-------------|-------------|-------------|
| `default` | Financial Services | `/root/.hermes/kanban.db` | Shared board for all financial tasks |
| `buddy-monitor` | Monitor Services | `/root/.hermes/kanban/boards/buddy-monitor/kanban.db` | Buddy ↔ Monitor orchestration |

### Board Metadata (`board.json`)

Each board directory contains a `board.json`:

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

The `name` field is the display name shown in the dashboard. It can be changed:

```bash
hermes kanban boards rename buddy-monitor "Monitor Services"
```

### Default Board Special Case

The default board lives at `/root/.hermes/kanban.db` (not under `boards/`). It has no directory and no `board.json`. Its display name is hardcoded as "Financial Services" in the dashboard service if no name file is found.

### Deleted Boards (Historical)

| Slug | Reason for Deletion |
|------|---------------------|
| `buddy-investor` | Empty — all cross-profile tasks use default board |
| `buddy-trader` | Empty — same reason |
| `buddy-fa` | Empty — same reason |

**Lesson:** Don't create per-profile boards. One shared `default` board handles all cross-profile tasks via the `assignee` field.

---

## Cross-Profile Dispatch

### How It Works

Every gateway process includes a built-in dispatcher that:

1. **Scans ALL boards** for tasks with `status='ready'` matching any valid assignee
2. **Claims tasks** atomically (prevents double-execution)
3. **Spawns workers** using `hermes -p <assignee> run --kanban <task_id>`

This means ANY gateway can spawn ANY profile's workers. The claim_lock mechanism prevents races.

### Verified Working Combination

| Task Created By | Assigned To | Dispawned By | Result |
|----------------|-------------|--------------|--------|
| buddy (buddy) | investor | investor gateway | ✅ Completed |
| buddy (buddy) | trader | trader gateway | ✅ Completed |
| buddy (buddy) | financialanalyst | FA gateway | ✅ Completed |
| buddy (buddy) | monitor | monitor gateway | ✅ Completed |

### Assignee Field

The `assignee` field in the tasks table stores the profile name. Valid values: `buddy`, `financialanalyst`, `investor`, `trader`, `monitor`.

Task without an assignee (`NULL`) are visible but never dispatched.

---

## Database Schema

### `tasks` Table

```sql
CREATE TABLE tasks (
    id                   TEXT PRIMARY KEY,
    title                TEXT NOT NULL,
    body                 TEXT,
    assignee             TEXT,              -- Profile name for dispatch
    status               TEXT NOT NULL,     -- triage|todo|ready|running|blocked|done|archived
    priority             INTEGER DEFAULT 0,
    created_by           TEXT,
    created_at           INTEGER NOT NULL,  -- Unix timestamp
    started_at           INTEGER,
    completed_at         INTEGER,
    workspace_kind       TEXT NOT NULL DEFAULT 'scratch',
    workspace_path       TEXT,
    branch_name          TEXT,
    claim_lock           TEXT,              -- UUID for atomic claim
    claim_expires        INTEGER,           -- Unix timestamp
    tenant               TEXT,
    result               TEXT,
    idempotency_key      TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    worker_pid           INTEGER,
    last_failure_error   TEXT,
    max_runtime_seconds  INTEGER,
    last_heartbeat_at    INTEGER,
    current_run_id       INTEGER,
    workflow_template_id TEXT,
    current_step_key     TEXT,
    skills               TEXT,              -- JSON array of skill names
    model_override       TEXT,
    max_retries          INTEGER,
    session_id           TEXT
)
```

### Key Indexes

```sql
CREATE INDEX idx_tasks_assignee_status ON tasks(assignee, status);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_session_id ON tasks(session_id);
```

### Status Values

| Status | Meaning |
|--------|---------|
| `triage` | Needs specification |
| `todo` | Waiting for dependencies |
| `ready` | Queued for dispatch |
| `running` | Being executed by worker |
| `blocked` | Needs human intervention |
| `done` | Completed successfully |
| `archived` | Hidden from UI (NOT `archived_at` column) |

> **IMPORTANT:** There is NO `archived_at` column. Archived tasks are identified by `status = 'archived'`, not by a timestamp column.

---

## CLI Reference

### Task Operations

```bash
# List all non-archived tasks
hermes kanban list

# Create a task (unassigned)
hermes kanban create "Task title" --body "Description"

# Create and assign to a profile
hermes kanban create "Monitor: Check disk space" \
  --assignee monitor \
  --body "Run df -h on all LXCs"

# Show task details
hermes kanban show <task_id>

# Show with comments/events (JSON)
hermes kanban show <task_id> --json

# Update task status
hermes kanban update <task_id> --status running

# Add comment
hermes kanban comment <task_id> "Progress update..."

# Archive task
hermes kanban archive <task_id>
```

### Board Operations

```bash
# List boards
hermes kanban boards

# Create board
hermes kanban boards create <slug> --name "Display Name"

# Rename board
hermes kanban boards rename <slug> "New Display Name"

# Delete board (destructive)
hermes kanban boards delete <slug>
```

### Worker Operations

```bash
# Manual dispatch (force immediate)
hermes kanban dispatch --profile <profile_id>

# With verbose logging
hermes kanban dispatch --profile <profile_id> -v

# Show dispatcher status
hermes kanban dispatcher
```

---

## Dashboard Integration

### Kanban Service (`services/kanban.py`)

The dashboard backend on CT 501 reads kanban data via SSH to CT 301:

```python
# CT 501 kanban service connects to CT 301:
ssh root@10.10.20.31 "python one-liner to query SQLite"
```

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/kanban/boards` | List all boards with task counts per status |
| `GET /api/kanban/tasks/{slug}` | Get tasks for a board |

### Display Name Resolution

1. Default board → checks `/root/.hermes/kanban/default-board-name.txt`, falls back to "Financial Services"
2. Other boards → reads `board.json` from board directory, extracts `.name` field

---

## Workflow Examples

### Example 1: Buddy Delegates to Monitor

```bash
# On CT 301, via buddy's CLI:
hermes kanban create "Monitor: Check all gateway processes" \
  --assignee monitor \
  --body "Run 'ps aux | grep hermes' on CT 301 and report status of all gateways."

# Monitor's gateway picks it up within 60 seconds
# Monitor executes the check and adds a comment with results
# Task status changes to 'done'
```

### Example 2: Cross-Profile Task with Verification

```bash
# Create a task for investor
hermes kanban create "Analyze AAPL Q2 earnings" \
  --assignee investor \
  --body "Pull latest AAPL earnings, run DCF analysis, post results"

# Investor gateway dispatches, processes, marks done
# Results visible in task comments
```

### Example 3: Multi-Step Workflow

```bash
# Step 1: Research (assign to trader)
hermes kanban create "Research semiconductor sector trends" \
  --assignee trader \
  --body "Compile 2025 semiconductor market trends and key players"

# Step 2: Analysis (assign to investor) - created after step 1 completes
hermes kanban create "DCF analysis on top 3 semiconductor picks" \
  --assignee investor \
  --body "Run DCF on the top 3 picks from the sector research"
```
