# Three-Layer Memory Architecture — Hermes Agent

> **Purpose:** Define clear roles for memory.md (layer 1), Hindsight (layer 2), and GitHub (layer 3) to create a scalable, hierarchical memory system that prevents redundant questions and enables long-term knowledge growth.

---

## Layer 1: Memory.md / USER.md (Volatile Working Memory)

**Purpose:** Dense, static facts needed in **every session**. This is the agent's "working set" — information that reduces the need for repeated user corrections.

**Characteristics:**
- **Size limit:** ~5,000 characters total (hard limit)
- **Update frequency:** Rare (only when user corrects or shares new stable preference)
- **Access:** Injected into every session automatically
- **Content type:** Declarative facts only (no procedures, no instructions)

**What belongs here:**
- User identity: name, role, Telegram ID, investment philosophy
- Infrastructure constants: Proxmox node IP, storage layout, key LXC IPs
- Profile summary: which models each profile uses, key configurations
- Communication preferences: brutal honesty, Damodaran framework, multi-model comparison
- Static conventions: memory_char_limit, user_char_limit, provider choices

**What does NOT belong here:**
- Task progress, TODO lists, session outcomes (use session_search)
- Temporary fixes, workarounds, debug info
- Procedures, command sequences, workflows (these go in skills)
- Anything that changes weekly or per-session

**Example good entry:**
```
Tae Telegram=2135517501, Nhoo=8748834444.
Profiles: buddy(Cohere/command-a-plus), investor(trader): google/gemma-4-31b-it:free via OpenRouter.
Memory config standardized: memory_char_limit=5000, user_char_limit=3000.
```

**Example bad entry (too verbose/procedural):**
```
Remember to always check the kanban board status by running 'hermes kanban list' before starting new work, and if there are blocked tasks, investigate them first.
```

---

## Layer 2: Hindsight (Searchable Long-Term Memory)

**Purpose:** Searchable accumulated knowledge from past sessions. This is the agent's "institutional memory" — facts, configurations, and lessons learned that aren't needed every session but are valuable for context.

**Characteristics:**
- **Storage:** 7 banks on CT301 localhost:8888 (PostgreSQL + vectors)
- **Access:** Via retain/recall API (POST /v1/default/banks/{bank_id}/memories)
- **Update frequency:** After major work sessions, configuration changes, or discoveries
- **Content type:** Facts, observations, configurations, error/solution pairs
- **Latency:** Retain takes 30-120s (LLM extraction), recall is fast (<1s)

**What belongs here:**
- Infrastructure changes: new LXCs, Caddy routing updates, DNS changes
- Configuration snapshots: Caddyfile, .env files, service configs (as observations)
- Lesson learned: mistakes with root cause and fix (from MISTAKES.md)
- System architecture: dashboard layout, kanban board structure, API endpoints
- Operational knowledge: how to check service health, restart procedures
- GitHub context: repo URLs, commit hashes, documentation locations
- Retains should be self-contained facts, not procedures

**What does NOT belong here:**
- Raw data dumps, logs, metrics (use Grafana/Prometheus)
- Step-by-step procedures (these belong in skills)
- Temporary session state, TODO lists, in-progress work
- Anything that will be stale in <7 days (use session_search instead)

**Example good entry:**
```
2026-05-31: Caddy (CT 103) reverse proxy routes monitor.271224.xyz:
- /dashboard/* → CT501:8080 FastAPI (strip_prefix)
- everything else → CT501:3000 Grafana
hermes.271224.xyz → CT301:9119 SPA direct (no proxy)
grafana.271224.xyz was removed — all dashboard panels now point to monitor.271224.xyz
```

**Example bad entry (too procedural):**
```
To update Caddy routing: 1) SSH to CT103, 2) edit /etc/caddy/Caddyfile, 3) run 'caddy reload', 4) test with curl.
```

---

## Layer 3: GitHub (Permanent Knowledge Base)

**Purpose:** Permanent, versioned knowledge base for complex documentation, diagrams, and runbooks that benefit from web browsing, searching, and long-term archival.

**Characteristics:**
- **Storage:** GitHub repository (public or private)
- **Access:** Via git clone, web browser, or API
- **Update frequency:** After major infrastructure changes, documentation updates, or lessons learned
- **Content type:** Markdown documents, diagrams, config samples, runbooks
- **Features:** Search, version history, branching, collaboration

**What belongs here:**
- Comprehensive documentation: DASHBOARD.md, KANBAN.md, NETWORK.md
- Architecture diagrams: DIAGRAMS.md (Mermaid, exportable to PNG/SVG)
- Mistakes & solutions: MISTAKES.md (detailed postmortems)
- Reference configs: references/ directory (live config snapshots)
- Runbooks: procedures for common operations (backup, restore, update)
- Diagrams: network maps, data flow sequences, component relationships
- Anything that benefits from: search, version control, web viewing, linking

**What does NOT belong here:**
- User-specific secrets (passwords, tokens, keys) — these stay encrypted/vaulted
- Raw machine output (logs, metrics) — these go to monitoring systems
- Temporary notes or scratch work
- Anything better served as a skill (procedural knowledge)

---

## Update Flow — How Information Moves Between Layers

```
User correction or new stable fact
        ↓
Layer 1: Memory.md/USER.md (if needed in every session)
        ↓
[If complex or searchable]
Layer 2: Hindsight retain (after major work/session)
        ↓
[If benefits from docs/diagrams/versioning]
Layer 3: GitHub commit (documentation, diagrams, runbooks)
```

**Decision guide when you learn something new:**
1. **Will I need this in every single session?** → Add to Memory.md/USER.md
2. **Will I need to search for this later (but not every session)?** → Retain to Hindsight
3. **Does this benefit from documentation, diagrams, or version control?** → Commit to GitHub
4. **Is this a procedure or workflow?** → Create/update a skill
5. **Is this temporary session context?** → Nothing (it will fade or use session_search)

---

## Maintenance Schedule

**After every major work session (5+ tool calls):**
1. Identify 1-3 key facts learned
2. Decide which layer(s) they belong to
3. Update Memory.md if it's a dense static fact
4. Retain to Hindsight if it's searchable accumulated knowledge
5. Consider if it belongs in GitHub documentation
6. Create/update a skill if it's a repeatable procedure

**Weekly:**
- Review Hindsight banks for stale facts (optional consolidation)
- Check GitHub repo for documentation gaps
- Review skills for outdated procedures

---

## Anti-Patterns to Avoid

❌ **Storing procedures in Memory.md** → makes it bloated and hard to scan  
❌ **Putting timestamps in Memory.md** → they become stale quickly  
❌ **Using Hindsight for TODO lists** → it's for facts, not task state  
❌ **Keeping secrets in any layer** → use encrypted vaults or .gitignore  
❌ **Writing novels in Memory.md** → respect the 5,000 char limit  
❌ **Forgetting to retain after major work** → knowledge evaporates  
❌ **Treating GitHub like a scratch pad** → it's for polished knowledge  

---

## Quick Reference Commands

**To add to Memory.md:**
```
memory action=add target=user content="New dense static fact here"
```

**To retain to Hindsight (fire-and-forget):**
```
terminal background=true notify_on_complete=false command="curl -s -X POST http://127.0.0.1:8888/v1/default/banks/hermes-buddy-2135517501/memories -H 'Content-Type: application/json' -d '{\"items\": [{\"content\": \"Your fact here\"}]}'"
```

**To retain to Hindsight (with completion notify):**
```
terminal background=true notify_on_complete=true command="curl -s -X POST http://127.0.0.1:8888/v1/default/banks/hermes-buddy-2135517501/memories -H 'Content-Type: application/json' -d '{\"items\": [{\"content\": \"Your fact here\"}]}'"
```

**To search Hindsight:**
```
session_search(query="your search term here", limit=3)  # Actually, use the Hindsight recall API directly in code
```

**To commit to GitHub:**
```
# In /tmp/hermes-hindsight-docs or your clone:
git add -A
git commit -m "docs: update description of what changed"
git push
```

---

**Remember:** The goal is to never have the user repeat themselves. Each layer reduces cognitive load:
- **Layer 1** prevents basic preference repetition
- **Layer 2** prevents re-explaining infrastructure/configuration
- **Layer 3** prevents re-documenting complex systems

---

### 2026-06-05 — Joplin Replaced by GitHub

Joplin Server (CT 403) was decommissioned. It was a redundant middle-man:
- Joplin sync script pushed MEMORY.md → Joplin LXC, but was one-way only
- Joplin never injected context back into Hermes sessions
- All structured documentation now lives in GitHub:
  - `thirawatk/house-infrastructure` — infrastructure docs (network, hardware, LXC)
  - `thirawatk/hermes-hindsight-docs` — Hindsight operations reference

**Result:** Simpler stack. No Joplin server, no sync scripts, no CT 403.
GitHub + Hindsight covers all documentation needs.


Use all three together for compound knowledge growth.