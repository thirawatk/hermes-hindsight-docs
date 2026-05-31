"""Kanban service — reads Hermes Kanban SQLite via SSH to CT 301."""
import subprocess
import json
import os

HOST = "10.10.20.31"
KANBAN_BASE = "/root/.hermes/kanban/boards"
DEFAULT_DB = "/root/.hermes/kanban.db"

def ssh_run(cmd):
    result = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
         "root@" + HOST, cmd],
        capture_output=True, text=True, timeout=15
    )
    return result.stdout.strip()

def _query_db(db_path, query):
    """Run a Python one-liner on CT 301 to query the SQLite DB."""
    py_script = f"""import sqlite3, json
conn = sqlite3.connect("{db_path}")
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("{query}")
result = [dict(r) for r in c.fetchall()]
print(json.dumps(result))
conn.close()"""
    import base64
    encoded = base64.b64encode(py_script.encode()).decode()
    out = ssh_run(f"echo '{encoded}' | base64 -d | python3")
    if not out:
        return []
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return []

def _get_board_name(slug, db_path):
    """Read display name from board.json metadata, fallback to slug."""
    if slug == "default":
        # Default board has no board.json; check for a name file
        name_file = os.path.join(os.path.dirname(db_path), "..", "default-board-name.txt")
        name = ssh_run(f"cat {name_file} 2>/dev/null").strip()
        if name:
            return name
        return "Financial Services"
    # Board directories have board.json
    board_json = os.path.join(os.path.dirname(db_path), "board.json")
    raw = ssh_run(f"cat {board_json} 2>/dev/null")
    if raw:
        try:
            meta = json.loads(raw)
            return meta.get("name", slug.replace("-", " ").title())
        except Exception:
            pass
    return slug.replace("-", " ").title()

def _get_db_paths():
    """Get all kanban.db paths including default and board dirs."""
    paths = []
    if ssh_run(f"test -f {DEFAULT_DB} && echo yes") == "yes":
        paths.append(("default", DEFAULT_DB))
    output = ssh_run(f"ls -d {KANBAN_BASE}/*/kanban.db 2>/dev/null")
    if output:
        for db_path in output.split("\n"):
            db_path = db_path.strip()
            if db_path:
                slug = os.path.basename(os.path.dirname(db_path))
                paths.append((slug, db_path))
    return paths

def get_boards():
    boards = []
    for slug, db_path in _get_db_paths():
        try:
            rows = _query_db(db_path,
                "SELECT status, COUNT(*) as cnt FROM tasks WHERE status != 'archived' GROUP BY status")
            counts = {}
            total = 0
            for row in rows:
                status = row.get("status", "unknown")
                cnt = row.get("cnt", 0)
                counts[status] = cnt
                total += cnt
            name = _get_board_name(slug, db_path)
            boards.append({
                "slug": slug,
                "name": name,
                "total": total,
                "counts": counts,
            })
        except Exception:
            boards.append({"slug": slug, "name": slug, "total": 0, "counts": {}})
    return boards

def get_tasks(board_slug, status_filter=None):
    if board_slug == "default":
        db_path = DEFAULT_DB
    else:
        db_path = f"{KANBAN_BASE}/{board_slug}/kanban.db"

    query = "SELECT id, title, body, assignee, status, created_at FROM tasks WHERE status != 'archived' ORDER BY created_at DESC"
    try:
        rows = _query_db(db_path, query)
        tasks = []
        for row in rows:
            if status_filter and row.get("status") != status_filter:
                continue
            tasks.append({
                "id": row.get("id"),
                "title": row.get("title"),
                "body": row.get("body"),
                "assignee": row.get("assignee"),
                "status": row.get("status"),
                "created_at": row.get("created_at"),
            })
        return tasks
    except Exception:
        return []
