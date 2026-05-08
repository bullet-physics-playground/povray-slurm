from flask import Flask, send_from_directory
from flask_socketio import SocketIO
import sqlite3
import json
import time
import os

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

_ENV_DB = os.environ.get('POVRAY_DB', 'render.db')
DB_FILE = os.path.abspath(_ENV_DB) if not os.path.isabs(_ENV_DB) else _ENV_DB
STATIC_DIR = os.path.abspath(".")

def get_db():
    if not os.path.isfile(DB_FILE):
        return None
    return sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)

def query_json(db, sql, params=()):
    try:
        cur = db.execute(sql, params)
        rows = cur.fetchall()
        return rows
    except Exception:
        return None

def fetch_progress(db):
    now = int(time.time())
    cutoff = now - 10
    rows = query_json(db, """
        SELECT node, COUNT(*) as total,
               SUM(CASE WHEN ts > ? THEN 1 ELSE 0 END) as recent
        FROM progress GROUP BY node
    """, (cutoff,))
    result = {}
    if rows:
        for node, total, recent in rows:
            recent = recent or 0
            fps = recent / 10.0
            result[node] = {"fps": round(fps, 2), "total": total}
    return result

def fetch_stats(db):
    rows = query_json(db, """
        SELECT node, cpu, mem, disk_r, disk_w, net_rx, net_tx, temp
        FROM node_stats
        WHERE (node, ts) IN (SELECT node, MAX(ts) FROM node_stats GROUP BY node)
    """)
    result = {}
    if rows:
        for node, cpu, mem, disk_r, disk_w, net_rx, net_tx, temp in rows:
            result[node] = {"cpu": cpu, "mem": mem, "disk_r": disk_r, "disk_w": disk_w,
                            "net_rx": net_rx, "net_tx": net_tx, "temp": temp}
    return result

def fetch_retry_info(db):
    total_retries = 0
    total_dead = 0
    row = query_json(db, "SELECT COUNT(*) FROM retry_log WHERE outcome='retry'")
    if row: total_retries = row[0][0]
    row = query_json(db, "SELECT COUNT(*) FROM retry_log WHERE outcome='dead'")
    if row: total_dead = row[0][0]
    rows = query_json(db, "SELECT node, outcome, COUNT(*) FROM retry_log GROUP BY node, outcome")
    by_node = {}
    if rows:
        for node, outcome, count in rows:
            if node not in by_node:
                by_node[node] = {"retries": 0, "dead": 0}
            by_node[node][outcome] = count
    return {"total_retries": total_retries, "total_dead": total_dead, "by_node": by_node}

def fetch_queue_sizes(db):
    pending = 0
    assigned = 0
    failed = 0
    dead = 0
    r = query_json(db, """
        SELECT COUNT(*) FROM frames f JOIN jobs j ON f.job_id=j.id
        WHERE f.status='pending' AND j.status='active'
    """)
    if r: pending = r[0][0]
    r = query_json(db, """
        SELECT COUNT(*) FROM frames f JOIN jobs j ON f.job_id=j.id
        WHERE f.status='assigned' AND j.status='active'
    """)
    if r: assigned = r[0][0]
    r = query_json(db, """
        SELECT COUNT(*) FROM frames f JOIN jobs j ON f.job_id=j.id
        WHERE f.status='failed' AND j.status='active'
    """)
    if r: failed = r[0][0]
    r = query_json(db, "SELECT COUNT(*) FROM frames WHERE status='dead'")
    if r: dead = r[0][0]
    return {"main": pending + assigned, "failed": failed, "dead": dead}

def fetch_all_jobs(db):
    cur = db.execute("""
        SELECT j.id, j.name, j.priority, j.total_frames, j.output_dir, j.status,
               COALESCE(SUM(CASE WHEN f.status='completed' THEN 1 ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN f.status='failed' THEN 1 ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN f.status='dead' THEN 1 ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN f.status='assigned' THEN 1 ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN f.status='pending' THEN 1 ELSE 0 END), 0)
        FROM jobs j LEFT JOIN frames f ON j.id = f.job_id
        WHERE j.status = 'active'
        GROUP BY j.id
        ORDER BY j.priority DESC, j.id ASC
    """)
    jobs = []
    for row in cur:
        jobs.append({"id": row[0], "name": row[1], "priority": row[2],
                     "total_frames": row[3], "output_dir": row[4], "status": row[5],
                     "completed": row[6], "failed": row[7], "dead": row[8],
                     "assigned": row[9], "pending": row[10]})
    return jobs

def fetch_errors(db, n=8):
    cur = db.execute(
        "SELECT ts, node, job_id, frame_number, attempt, message FROM error_log ORDER BY id DESC LIMIT ?",
        (n,)
    )
    lines = []
    for row in reversed(list(cur)):
        ts, node, job_id, frame_number, attempt, message = row
        parts = [str(ts), node]
        if job_id is not None and frame_number is not None:
            parts.append(f"frame={job_id}:{frame_number}")
        if attempt:
            parts.append(f"attempt={attempt}")
        parts.append(message)
        lines.append(' '.join(parts))
    return lines

def watcher():
    while True:
        data = {}
        db = get_db()
        if db:
            try:
                data.update(fetch_progress(db))
            except Exception:
                pass

            try:
                stats = fetch_stats(db)
                for node, s in stats.items():
                    if node not in data:
                        data[node] = {}
                    data[node]["stats"] = s
            except Exception:
                pass

            try:
                retry_info = fetch_retry_info(db)
                for node, r in retry_info.get("by_node", {}).items():
                    if node not in data:
                        data[node] = {}
                    data[node]["retries"] = r.get("retries", 0)
                    data[node]["dead"] = r.get("dead", 0)
                data["_retry"] = {
                    "total_retries": retry_info.get("total_retries", 0),
                    "total_dead": retry_info.get("total_dead", 0),
                }
            except Exception:
                pass

            try:
                qs = fetch_queue_sizes(db)
                if qs:
                    data["_queues"] = qs
            except Exception:
                pass

            try:
                all_jobs = fetch_all_jobs(db)
                if all_jobs:
                    data["_queued_jobs"] = all_jobs
                else:
                    data["_queued_jobs"] = []
            except Exception:
                pass

            try:
                errs = fetch_errors(db, 8)
                if errs:
                    data["_errors"] = errs
            except Exception:
                pass

            db.close()
        socketio.emit("update", data)
        socketio.sleep(1)

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index_ws.html")

if __name__ == "__main__":
    socketio.start_background_task(watcher)
    socketio.run(app, host="0.0.0.0", port=5000)
