# Hindsight Operations Runbook

## Daily Health Check

Run this to verify everything is healthy:

```bash
#!/bin/bash
echo "=== Hindsight Health Check ==="
echo ""

# API Health
echo -n "API: "
curl -s http://127.0.0.1:8888/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'{d[\"status\"]} (db: {d[\"database\"]})')"

# Banks
echo ""
echo "Banks:"
curl -s http://127.0.0.1:8888/v1/default/banks | python3 -c "
import sys,json
for b in json.load(sys.stdin)['banks']:
    print(f'  {b[\"bank_id\"]}: name={b.get(\"name\",\"?\")}')"

# Gateways
echo ""
echo "Gateways:"
for p in buddy financialanalyst investor trader monitor; do
  pid_file=~/.hermes/profiles/$p/gateway.pid
  if [ -f "$pid_file" ]; then
    pid=$(python3 -c "import json; print(json.load(open('$pid_file'))['pid'])")
    if [ -d "/proc/$pid" ]; then
      echo "  $p: PID $pid ✅"
    else
      echo "  $p: PID $pid ❌ (stale)"
    fi
  else
    echo "  $p: NO PID FILE ❌"
  fi
done

# Systemd
echo ""
echo -n "Hindsight systemd: "
systemctl is-active hindsight-api.service
```

Save as `~/bin/hindsight-health.sh` and run with `bash ~/bin/hindsight-health.sh`.

## Common Operations

### Test a Bank Manually

```bash
BANK="hermes-buddy-2135517501"

# Write a test memory
curl -s -X POST http://127.0.0.1:8888/v1/default/banks/$BANK/memories \
  -H "Content-Type: application/json" \
  -d '{"items":[{"content":"Manual test entry at $(date -Iseconds)"}]}' \
  | python3 -m json.tool

# Wait 2s for indexing, then recall
sleep 2
curl -s -X POST http://127.0.0.1:8888/v1/default/banks/$BANK/memories/recall \
  -H "Content-Type: application/json" \
  -d '{"query":"manual test entry","max_tokens":200}' \
  | python3 -m json.tool
```

### Add a New Profile

1. Create the profile: `hermes profile create <name>`
2. Add to `config.yaml`:
   ```yaml
   memory:
     provider: hindsight
     memory_enabled: true
     memory_char_limit: 2200
     user_char_limit: 1375
     user_profile_enabled: true
     hindsight:
       api_url: http://127.0.0.1:8888
       bank_id: hermes-<name>-<user_id>
   ```
3. Add to `.env`:
   ```bash
   HINDSIGHT_MODE=local
   HINDSIGHT_API_URL=http://127.0.0.1:8888
   HINDSIGHT_BANK_ID=hermes-<name>-<user_id>
   HINDSIGHT_BUDGET=mid
   ```
4. Start gateway: `hermes gateway start --profile <name>`
5. Verify: `curl -s http://127.0.0.1:8888/v1/default/banks/hermes-<name>-<user_id>/stats`

### Convert Single-User to Multi-User

For a profile that needs to serve multiple users (like FA):

1. Change `config.yaml`:
   ```yaml
   # FROM:
   hindsight:
     bank_id: hermes-<name>-<user_id>
   # TO:
   hindsight:
     bank_id_template: hermes-<name>-{user}
   ```
2. Add `flush_min_turns: 6` and `nudge_interval: 10` for multi-user optimization
3. Remove `HINDSIGHT_BANK_ID` from `.env` (template handles it dynamically)
4. Restart gateway: `hermes gateway restart --profile <name>`

### Migrate Data Between Banks

```bash
# 1. Export source bank memories
curl -s -X POST http://127.0.0.1:8888/v1/default/banks/<source>/memories/recall \
  -H "Content-Type: application/json" \
  -d '{"query":"","max_tokens":10000}' > /tmp/memories_export.json

# 2. Extract content and retain to target
python3 -c "
import json
data = json.load(open('/tmp/memories_export.json'))
items = [{'content': r['text']} for r in data.get('results', [])]
print(json.dumps({'items': items}))
" > /tmp/memories_import.json

curl -s -X POST http://127.0.0.1:8888/v1/default/banks/<target>/memories \
  -H "Content-Type: application/json" \
  -d @/tmp/memories_import.json
```

### Handle Stuck Operations

```bash
# List pending/failed operations
curl -s http://127.0.0.1:8888/v1/default/banks/<bank_id>/operations \
  | python3 -m json.tool

# Retry a failed operation
curl -s -X POST http://127.0.0.1:8888/v1/default/banks/<bank_id>/operations/<op_id>/retry

# Cancel a pending operation
curl -s -X DELETE http://127.0.0.1:8888/v1/default/banks/<bank_id>/operations/<op_id>
```

### Backup a Bank

```bash
# Export all memories
curl -s -X POST http://127.0.0.1:8888/v1/default/banks/<bank_id>/memories/recall \
  -H "Content-Type: application/json" \
  -d '{"query":"","max_tokens":50000}' \
  > backup_$(date +%Y%m%d)_<bank_id>.json

# Also export the bank template (config + directives)
curl -s http://127.0.0.1:8888/v1/default/banks/<bank_id>/export \
  > backup_$(date +%Y%m%d)_<bank_id>_template.json
```

### Restore a Bank

```bash
# Import template (creates bank with config)
curl -s -X POST http://127.0.0.1:8888/v1/default/banks/<bank_id>/import \
  -H "Content-Type: application/json" \
  -d @backup_template.json

# Re-retain memories from backup
python3 -c "
import json
data = json.load(open('backup_memories.json'))
items = [{'content': r['text']} for r in data.get('results', [])]
# Batch in groups of 10
for i in range(0, len(items), 10):
    batch = items[i:i+10]
    print(json.dumps({'items': batch}))
" | while read batch; do
  curl -s -X POST http://127.0.0.1:8888/v1/default/banks/<bank_id>/memories \
    -H "Content-Type: application/json" \
    -d "$batch"
  sleep 1
done
```

## Troubleshooting

### Gateway Can't Connect to Hindsight

**Symptom:** Gateway logs show connection refused to `127.0.0.1:8888`

**Fix:**
```bash
# Check if Hindsight API is running
systemctl status hindsight-api.service

# If not running
sudo systemctl start hindsight-api.service

# If failed
sudo systemctl restart hindsight-api.service
journalctl -u hindsight-api.service --no-pager -n 50
```

### Bank Returns 0 Results

**Symptom:** Recall returns empty results even though memories were stored

**Causes & Fixes:**
1. **Bank doesn't exist** — First retain auto-creates it. Run a test retain.
2. **Async indexing not complete** — Wait 2-3 seconds after retain before recall.
3. **Query too specific** — Try broader query terms.
4. **Bank was cleared** — Check `total_nodes` in stats endpoint.

### High Memory Usage in Gateway

**Symptom:** Gateway process using excessive RAM

**Fix:**
```bash
# Restart the gateway
hermes gateway restart --profile <name>

# If persistent, check for memory leaks in sessions
ls -la ~/.hermes/profiles/<name>/sessions/ | wc -l
```

### Stale PID Files

**Symptom:** PID file exists but process is dead

**Fix:**
```bash
# Remove stale PID and lock files
rm ~/.hermes/profiles/<name>/gateway.pid
rm ~/.hermes/profiles/<name>/gateway.lock

# Restart
hermes gateway start --profile <name>
```

### Hindsight API Won't Start

**Symptom:** `systemctl start hindsight-api.service` fails

**Fix:**
```bash
# Check logs
journalctl -u hindsight-api.service --no-pager -n 100

# Common issue: PostgreSQL not running
systemctl status postgresql
sudo systemctl start postgresql

# Common issue: Port already in use
ss -tlnp | grep 8888

# Check config
cat ~/.hermes/hindsight/config.json | python3 -m json.tool
```

## Monitoring

### Key Metrics to Watch

| Metric | Where | Warning Threshold |
|--------|-------|-------------------|
| `pending_operations` | Bank stats | > 5 for > 1 hour |
| `failed_operations` | Bank stats | > 0 |
| `total_nodes` | Bank stats | > 10000 (consider consolidation) |
| Gateway memory | `ps aux` | > 500MB per gateway |
| API response time | Manual curl | > 5s for recall |

### Prometheus Metrics

Hindsight exposes Prometheus metrics at `GET /metrics`:

```bash
curl -s http://127.0.0.1:8888/metrics
```

Key metrics:
- `hindsight_recall_duration_seconds` — Recall latency
- `hindsight_retain_duration_seconds` — Retain latency
- `hindsight_operations_total` — Operation count by status
