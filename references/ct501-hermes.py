"""Hermes service — gateway status, storage, bank stats via SSH to CT 301."""
import json
import re
import subprocess

HOST = "10.10.20.31"

def ssh_run(cmd):
    result = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
         f"root@{HOST}", cmd],
        capture_output=True, text=True, timeout=15
    )
    return result.stdout.strip()

def get_gateway_status():
    profiles = ["buddy", "financialanalyst", "investor", "trader", "monitor", "default"]
    result = {"profiles": [], "overall": "unknown"}

    # Get gateway processes: PID and full command line
    ps_out = ssh_run(
        "ps -eo pid,comm,args | grep 'hermes_cli.main' | grep 'gateway' | grep -v grep"
    )

    # Parse: PID COMM ARGS...
    gw_pids = {}
    for line in ps_out.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 2)  # pid, comm, args
        if len(parts) < 3:
            continue
        pid, comm, args = parts[0], parts[1], parts[2]
        # Check if this is a gateway process run
        if "gateway" not in args and "gateway" not in comm:
            continue
        # Determine profile
        m = re.search(r'--profile\s+(\S+)', args)
        if m:
            gw_pids[m.group(1)] = pid
        else:
            # No --profile = default
            gw_pids["default"] = pid

    for profile in profiles:
        p = {"name": profile, "status": "offline", "pid": None, "cpu": 0.0, "mem": 0.0}
        if profile in gw_pids:
            pid = gw_pids[profile]
            p["status"] = "running"
            p["pid"] = pid
            stat = ssh_run(f"ps -p {pid} -o pcpu,rss --no-headers 2>/dev/null || echo '0.0 0'")
            vals = stat.strip().split()
            if len(vals) >= 2:
                try:
                    p["cpu"] = float(vals[0])
                    p["mem"] = round(int(vals[1]) / 1024, 1)
                except ValueError:
                    pass
        result["profiles"].append(p)

    running = sum(1 for p in result["profiles"] if p["status"] == "running")
    result["overall"] = f"{running}/{len(profiles)} running"
    return result

def get_storage():
    result = []
    for mount, label in {"/": "rpool", "/mnt/hindsight": "ssd-vault"}.items():
        out = ssh_run(f"df -h {mount} | tail -1")
        parts = out.split()
        if len(parts) >= 5:
            result.append({
                "label": label, "mount": mount,
                "size": parts[1], "used": parts[2], "available": parts[3],
                "use_pct": int(parts[4].rstrip("%")),
            })
    return result

def get_hindsight_health():
    try:
        out = ssh_run("curl -s http://127.0.0.1:8888/health")
        h = json.loads(out)
        return {"status": h.get("status", "?"), "database": h.get("database", "?")}
    except Exception as e:
        return {"status": "unreachable", "error": str(e)}

def get_bank_stats():
    try:
        out = ssh_run("curl -s http://127.0.0.1:8888/v1/default/banks")
        banks = json.loads(out).get("banks", [])
        result = []
        for b in banks:
            bid = b["bank_id"]
            try:
                so = ssh_run(f"curl -s http://127.0.0.1:8888/v1/default/banks/{bid}/stats")
                stats = json.loads(so)
                result.append({
                    "bank_id": bid,
                    "nodes": stats.get("total_nodes", 0),
                    "docs": stats.get("total_documents", 0),
                    "observations": stats.get("total_observations", 0),
                    "last_consolidated": stats.get("last_consolidated_at"),
                })
            except Exception:
                result.append({"bank_id": bid, "nodes": 0, "docs": 0, "observations": 0})
        return result
    except Exception:
        return []
