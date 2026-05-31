# Architecture Diagrams

> Mermaid diagrams for the Hermes Agent infrastructure.

---

## Complete System Architecture

```mermaid
graph TB
    subgraph INTERNET["☁️ Internet"]
        BROWSER[🌐 User Browser]
        CF_TUNNEL[🔒 Cloudflare Tunnel<br/>*.271224.xyz]
    end

    subgraph PROX["🖥️ Proxmox Node 1 (10.10.20.11)"]
        
        subgraph CT103["📦 CT 103 — Caddy (10.10.20.23)"]
            CADDY[🔀 Caddy Reverse Proxy<br/>HTTPS + Auto-TLS]
        end

        subgraph CT301["📦 CT 301 — Hermes (10.10.20.31)"]
            subgraph GATEWAYS["Gateway Processes"]
                GW_BUDDY[🤖 buddy gateway]
                GW_FA[🤖 financialanalyst gateway]
                GW_INV[🤖 investor gateway]
                GW_TRD[🤖 trader gateway]
                GW_MON[🤖 monitor gateway]
                GW_DEF[🤖 default gateway]
            end
            
            subgraph SERVICES["Services"]
                SPA[📊 Hermes SPA :9119]
                HINDSIGHT[🧠 Hindsight API :8888]
            end

            subgraph STORAGE["Storage"]
                KANBAN_DB[(📋 kanban.db<br/>Financial Services)]
                MON_DB[(📋 buddy-monitor/kanban.db<br/>Monitor Services)]
                PG[(🐘 PostgreSQL<br/>Memory Banks)]
                RPOOL[💾 rpool 20GB<br/>OS + Hermes]
                SSD[💾 ssd-vault 923GB<br/>Hindsight Data]
            end
        end

        subgraph CT501["📦 CT 501 — Monitor (10.10.20.51)"]
            GRAFANA[📈 Grafana :3000]
            FASTAPI[⚡ FastAPI Dashboard :8080]
            SERVICES_MOD["services/<br/>  hermes.py<br/>  hindsight.py<br/>  kanban.py"]
        end

        subgraph OTHER["Other LXCs"]
            DNS[🌐 CT 102 — DNS]
            PAPER[📄 CT 402 — Paperless]
            JOPLIN[📝 CT 403 — Joplin]
            CWA[📦 CT 404 — CWA]
        end
    end

    %% Internet to Proxmox
    BROWSER -->|"HTTPS"| CF_TUNNEL -->|"Tunnel"| CADDY

    %% Caddy routing
    CADDY -->|"monitor.271224.xyz/dashboard/*<br/>(strip_prefix)"| FASTAPI
    CADDY -->|"monitor.271224.xyz/*<br/>(everything else)"| GRAFANA
    CADDY -->|"hermes.271224.xyz<br/>(direct)"| SPA

    %% CT 501 internal
    GRAFANA -->|"iframe panels<br/>HTTPS links"| CADDY
    FASTAPI -->|"SSH"| CT301

    %% SSH data collection
    SERVICES_MOD -->|"SSH query"| GW_BUDDY
    SERVICES_MOD -->|"SSH query"| HINDSIGHT
    SERVICES_MOD -->|"SSH query"| KANBAN_DB

    %% CT 301 internal
    GW_BUDDY -->|"recall/retain"| HINDSIGHT
    GW_FA -->|"recall/retain"| HINDSIGHT
    GW_INV -->|"recall/retain"| HINDSIGHT
    GW_TRD -->|"recall/retain"| HINDSIGHT
    GW_MON -->|"recall/retain"| HINDSIGHT

    HINDSIGHT -->|"read/write"| PG
    GW_BUDDY -->|"create tasks"| KANBAN_DB
    GW_MON -->|"claim/exec"| MON_DB

    %% Storage
    RPOOL -.->|"hosts"| GATEWAYS
    SSD -.->|"hosts"| PG
```

---

## Dashboard Data Flow

```mermaid
sequenceDiagram
    participant B as 🌐 Browser
    participant C as 🔀 Caddy (CT 103)
    participant F as ⚡ FastAPI (CT 501)
    participant S as 🔑 SSH
    participant H as 🖥️ CT 301

    Note over B,H: Dashboard Kanban Page Load

    B->>C: GET monitor.271224.xyz/dashboard/kanban
    C->>C: strip_prefix /dashboard
    C->>F: GET /kanban
    F->>F: render kanban.html
    F->>S: services.kanban.get_boards()
    S->>H: ssh root@10.10.20.31
    H->>H: python3 query kanban.db
    H-->>S: JSON board list
    S-->>F: board list
    F-->>C: HTML response
    C-->>B: HTML with board names

    Note over B,H: JS fetches task data

    B->>B: fetch('api/kanban/tasks/default')
    B->>C: GET dashboard/api/kanban/tasks/default
    C->>C: strip_prefix /dashboard
    C->>F: GET /api/kanban/tasks/default
    F->>S: services.kanban.get_tasks("default")
    S->>H: ssh + python3 query
    H-->>S: JSON task list
    F-->>C: JSON response
    C-->>B: JSON → render table
```

---

## SPA Data Flow

```mermaid
sequenceDiagram
    participant B as 🌐 Browser
    participant C as 🔀 Caddy (CT 103)
    participant SPA as 📊 Hermes SPA (CT 301)

    Note over B,SPA: SPA Direct Access (no proxy)

    B->>C: GET hermes.271224.xyz/
    C->>SPA: reverse_proxy ALL traffic
    SPA-->>B: SPA HTML shell

    B->>B: fetch('/api/profiles')
    B->>C: GET hermes.271224.xyz/api/profiles
    C->>SPA: /api/profiles
    SPA->>SPA: Query gateway status
    SPA-->>B: JSON profiles data
```

---

## Cross-Profile Kanban Dispatch

```mermaid
sequenceDiagram
    participant BUDDY as 🤖 buddy (orchestrator)
    participant DB as 📋 kanban.db (CT 301)
    participant DISPATCH as 📡 monitor gateway dispatcher
    participant WORKER as 👷 monitor worker

    Note over BUDDY,WORKER: Task creation → dispatch → execution

    BUDDY->>DB: INSERT task (status='ready', assignee='monitor')
    
    Note over DISPATCH: Every 60 seconds...
    DISPATCH->>DB: SELECT * FROM tasks WHERE status='ready' AND assignee='monitor'
    DB-->>DISPATCH: [task1, task2, ...]
    DISPATCH->>DB: UPDATE claim_lock=<uuid> WHERE claim_lock IS NULL

    alt claim succeeds
        DISPATCH->>WORKER: Spawn: hermes -p monitor run --kanban <task_id>
        WORKER->>DB: UPDATE status='running'
        WORKER->>WORKER: Execute task
        WORKER->>DB: UPDATE status='done', add comment
    else claim fails (already taken)
        DISPATCH->>DISPATCH: Skip, wait for next tick
    end
```

---

## Memory System (Hindsight)

```mermaid
graph LR
    subgraph AGENTS["Gateway Processes"]
        BUDDY[🤖 buddy]
        FA[🤖 FA]
        INV[🤖 investor]
        TRD[🤖 trader]
        MON[🤖 monitor]
    end

    subgraph HINDSIGHT["🧠 Hindsight API (CT 301 :8888)"]
        API[API Server]
        LLM[LLM Extraction<br/>OpenRouter/owl-alpha]
        EMB[Embeddings<br/>Cohere]
    end

    subgraph PG["🐘 PostgreSQL (ssd-vault)"]
        BANK_B[(hermes-buddy-2135517501)]
        BANK_FA[(hermes-financialanalyst-2135517501)]
        BANK_FAN[(hermes-financialanalyst-8748834444)]
        BANK_I[(hermes-investor-2135517501)]
        BANK_T[(hermes-trader-2135517501)]
        BANK_M[(hermes-monitor-2135517501)]
    end

    BUDDY -->|"retain/recall"| API
    FA -->|"retain/recall"| API
    INV -->|"retain/recall"| API
    TRD -->|"retain/recall"| API
    MON -->|"retain/recall"| API

    API -->|"extract facts"| LLM
    API -->|"embed query"| EMB
    API -->|"read/write"| PG

    BANK_B -.->|"14 nodes"| API
    BANK_FA -.->|"5 nodes"| API
    BANK_FAN -.->|"2 nodes"| API
    BANK_I -.->|"4 nodes"| API
    BANK_T -.->|"4 nodes"| API
    BANK_M -.->|"4 nodes"| API
```

---

## Multi-Layer Memory

```mermaid
graph TB
    subgraph LAYER1["Layer 1: Memory Tool (MEMORY.md / USER.md)"]
        MEM[📝 5,000 chars/profile<br/>Dense vital facts<br/>Injected every session]
    end

    subgraph LAYER2["Layer 2: Hindsight Banks"]
        BANKS[🧠 Unlimited storage<br/>923 GB ssd-vault<br/>Auto-recalled each turn]
    end

    subgraph LAYER3["Layer 3: GitHub Docs"]
        DOCS[📚 Unlimited docs<br/>Version-controlled<br/>Procedures & runbooks]
    end

    MEM -->|"survives restart<br/>limited capacity"| AGENT
    BANKS -->|"auto-retain/recall<br/>query explicitly"| AGENT
    DOCS -->|"manual reference<br/>offline backup"| AGENT

    style LAYER1 fill:#e1f5fe
    style LAYER2 fill:#f3e5f5
    style LAYER3 fill:#e8f5e9
```

---

## Caddy Routing Decision Tree

```mermaid
graph TD
    CF[Cloudflare Tunnel<br/>*.271224.xyz] --> CADDY

    CADDY{Request Host Header}

    CADDY -->|monitor.271224.xyz| PATH{Path starts with<br/>/dashboard/?}
    PATH -->|Yes| STRIP[strip_prefix /dashboard]
    STRIP --> FASTAPI[⚡ CT 501:8080<br/>FastAPI Dashboard]
    PATH -->|No| GRAFANA[📈 CT 501:3000<br/>Grafana]

    CADDY -->|hermes.271224.xyz| SPA[📊 CT 301:9119<br/>Hermes SPA]

    CADDY -->|*.271224.xyz| OTHER[Other CTs]

    style FASTAPI fill:#bbdefb
    style GRAFANA fill:#fff9c4
    style SPA fill:#c8e6c9
```
