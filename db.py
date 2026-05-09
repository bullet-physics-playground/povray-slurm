#!/usr/bin/env python3
import sqlite3
import sys
import os
import time
import json
import signal

_ENV_DB = os.environ.get('POVRAY_DB', 'render.db')
DB_FILE = os.path.abspath(_ENV_DB) if not os.path.isabs(_ENV_DB) else _ENV_DB
MAX_RETRIES = 3
BACKOFF_BASE = 5
DB_RETRY_DELAY = 2

def get_db():
    db = sqlite3.connect(DB_FILE, isolation_level=None)
    db.execute("PRAGMA busy_timeout=60000")
    db.execute("PRAGMA synchronous=FULL")
    migrate(db)
    return db

def get_db_readonly():
    return sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)

def retry_on_lock(fn, *args, **kwargs):
    for attempt in range(10):
        try:
            return fn(*args, **kwargs)
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
            msg = str(e)
            if attempt < 9:
                time.sleep(DB_RETRY_DELAY * (attempt + 1))
                continue
            raise

def migrate(db):
    cur = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
    if cur.fetchone():
        return
    cur = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='frames'")
    old_frames = cur.fetchone() is not None
    old_total = 0
    old_par = '4'
    old_threads = '1'
    if old_frames:
        try:
            old_total = db.execute("SELECT COUNT(*) FROM frames").fetchone()[0]
            old_par = db.execute("SELECT value FROM config WHERE key='par'").fetchone()
            old_par = old_par[0] if old_par else '4'
            old_threads = db.execute("SELECT value FROM config WHERE key='threads'").fetchone()
            old_threads = old_threads[0] if old_threads else '1'
        except Exception:
            pass
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','completed','cancelled')),
            total_frames INTEGER NOT NULL,
            width INTEGER,
            height INTEGER,
            output_dir TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS frames (
            job_id INTEGER NOT NULL,
            frame_number INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','assigned','completed','failed','dead')),
            node TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (job_id, frame_number),
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        );
        CREATE TABLE IF NOT EXISTS progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            node TEXT NOT NULL,
            job_id INTEGER NOT NULL,
            frame_number INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS node_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            node TEXT NOT NULL,
            cpu REAL, mem REAL, disk_r INTEGER, disk_w INTEGER,
            net_rx INTEGER, net_tx INTEGER, temp REAL
        );
        CREATE TABLE IF NOT EXISTS error_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            node TEXT NOT NULL,
            job_id INTEGER,
            frame_number INTEGER,
            attempt INTEGER,
            message TEXT
        );
        CREATE TABLE IF NOT EXISTS retry_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            node TEXT NOT NULL,
            job_id INTEGER NOT NULL,
            frame_number INTEGER NOT NULL,
            attempt INTEGER NOT NULL,
            outcome TEXT NOT NULL CHECK (outcome IN ('retry','dead'))
        );
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    if old_frames and old_total > 0:
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("INSERT INTO jobs(id, name, priority, status, total_frames) VALUES (1, 'Legacy Job', 0, 'active', ?)", (old_total,))
            try:
                rows = db.execute("SELECT id, status, node, attempts, last_error FROM frames").fetchall()
                for row in rows:
                    db.execute(
                        "INSERT INTO frames(job_id, frame_number, status, node, attempts, last_error) VALUES (1, ?, ?, ?, ?, ?)",
                        (row[0], row[1], row[2], row[3], row[4])
                    )
            except Exception:
                pass
            db.execute("INSERT OR REPLACE INTO config(key, value) VALUES ('par', ?)", (old_par,))
            db.execute("INSERT OR REPLACE INTO config(key, value) VALUES ('threads', ?)", (old_threads,))
            db.commit()
        except Exception:
            db.rollback()
            raise
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("INSERT OR IGNORE INTO config(key, value) VALUES ('par', '4')")
        db.execute("INSERT OR IGNORE INTO config(key, value) VALUES ('threads', '1')")
        db.commit()
    except Exception:
        db.rollback()
        raise

def parse_frame_ref(ref):
    if ':' in ref:
        job_str, num_str = ref.split(':', 1)
        return int(job_str), int(num_str)
    return 1, int(ref)

def cmd_init(args):
    db = get_db()
    db.execute("DELETE FROM frames")
    db.execute("DELETE FROM progress")
    db.execute("DELETE FROM node_stats")
    db.execute("DELETE FROM error_log")
    db.execute("DELETE FROM retry_log")
    db.execute("DELETE FROM jobs")
    print("Tables cleared. Use 'job-create' to add jobs.")

def cmd_job_create(args):
    if len(args) < 3:
        print("Usage: job-create <name> <priority> <total_frames> [width] [height]", file=sys.stderr)
        return
    name = args[0]
    priority = int(args[1])
    total_frames = int(args[2])
    width = int(args[3]) if len(args) > 3 else None
    height = int(args[4]) if len(args) > 4 else None
    db = get_db()
    cur = db.execute(
        "INSERT INTO jobs(name, priority, status, total_frames, width, height) VALUES (?, ?, 'active', ?, ?, ?)",
        (name, priority, total_frames, width, height)
    )
    job_id = cur.lastrowid
    output_dir = f"frames/job_{job_id}_{name.replace(' ', '_')}"
    db.execute("UPDATE jobs SET output_dir = ? WHERE id = ?", (output_dir, job_id))
    for i in range(1, total_frames + 1):
        db.execute("INSERT INTO frames(job_id, frame_number, status) VALUES (?, ?, 'pending')", (job_id, i))
    print(job_id)

def cmd_job_list(args):
    db = get_db_readonly()
    cur = db.execute("""
        SELECT j.id, j.name, j.priority, j.status, j.total_frames,
               COALESCE(SUM(CASE WHEN f.status='completed' THEN 1 ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN f.status='failed' THEN 1 ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN f.status IN ('pending','assigned') THEN 1 ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN f.status='dead' THEN 1 ELSE 0 END), 0)
        FROM jobs j LEFT JOIN frames f ON j.id = f.job_id
        GROUP BY j.id ORDER BY j.priority DESC, j.id ASC
    """)
    result = []
    for row in cur:
        result.append({
            "id": row[0], "name": row[1], "priority": row[2], "status": row[3],
            "total": row[4], "completed": row[5], "failed": row[6],
            "remaining": row[7], "dead": row[8]
        })
    print(json.dumps(result))

def cmd_current_job(args):
    db = get_db_readonly()
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
        LIMIT 1
    """)
    row = cur.fetchone()
    if row:
        print(json.dumps({
            "id": row[0], "name": row[1], "priority": row[2],
            "total_frames": row[3], "output_dir": row[4], "status": row[5],
            "completed": row[6], "failed": row[7], "dead": row[8],
            "assigned": row[9], "pending": row[10]
        }))
    else:
        print(json.dumps({}))

def cmd_job_info(args):
    if not args:
        return
    job_id = int(args[0])
    db = get_db_readonly()
    cur = db.execute("SELECT id, name, priority, total_frames, output_dir, status, width, height FROM jobs WHERE id=?", (job_id,))
    row = cur.fetchone()
    if row:
        print(json.dumps({
            "id": row[0], "name": row[1], "priority": row[2],
            "total_frames": row[3], "output_dir": row[4], "status": row[5],
            "width": row[6], "height": row[7]
        }))
    else:
        print(json.dumps({}))

def cmd_frame_info(args):
    if not args:
        return
    job_id, frame_number = parse_frame_ref(args[0])
    db = get_db_readonly()
    cur = db.execute("""
        SELECT f.job_id, f.frame_number, j.total_frames, j.output_dir, j.name, j.priority, j.id
        FROM frames f JOIN jobs j ON f.job_id = j.id
        WHERE f.job_id = ? AND f.frame_number = ?
    """, (job_id, frame_number))
    row = cur.fetchone()
    if row:
        print(f"{row[0]} {row[1]} {row[2]} {row[3]} {row[4]} {row[5]}")
    else:
        print("0 0 0 . unknown 0")

def cmd_dequeue(args):
    if not args:
        return
    hostname = args[0]
    db = get_db()
    cur = db.execute("""
        UPDATE frames SET status='assigned', node=?, updated_at=datetime('now')
        WHERE (job_id, frame_number) = (
            SELECT f.job_id, f.frame_number FROM frames f
            JOIN jobs j ON f.job_id = j.id
            WHERE f.status = 'pending' AND j.status = 'active'
            ORDER BY j.created_at ASC, f.frame_number ASC
            LIMIT 1
        )
        RETURNING job_id, frame_number
    """, (hostname,))
    row = cur.fetchone()
    if row:
        print(f"{row[0]}:{row[1]}")
        return
    cur = db.execute("""
        UPDATE frames SET status='assigned', node=?, updated_at=datetime('now')
        WHERE (job_id, frame_number) = (
            SELECT f.job_id, f.frame_number FROM frames f
            JOIN jobs j ON f.job_id = j.id
            WHERE f.status = 'failed' AND j.status = 'active' AND f.node != ?
            ORDER BY j.created_at ASC, f.frame_number ASC
            LIMIT 1
        )
        RETURNING job_id, frame_number
    """, (hostname, hostname))
    row = cur.fetchone()
    if row:
        print(f"{row[0]}:{row[1]}")
        return

def cmd_complete(args):
    if len(args) < 2:
        return
    job_id, frame_number = parse_frame_ref(args[0])
    hostname = args[1]
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "UPDATE frames SET status='completed', node=?, updated_at=datetime('now') WHERE job_id=? AND frame_number=?",
            (hostname, job_id, frame_number)
        )
        db.execute(
            "INSERT INTO progress(ts, node, job_id, frame_number) VALUES (?, ?, ?, ?)",
            (int(time.time()), hostname, job_id, frame_number)
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

def cmd_fail(args):
    if len(args) < 3:
        return
    job_id, frame_number = parse_frame_ref(args[0])
    hostname = args[1]
    message = ' '.join(args[2:])
    db = get_db()
    cur = db.execute("SELECT attempts FROM frames WHERE job_id=? AND frame_number=?", (job_id, frame_number))
    row = cur.fetchone()
    if not row:
        return
    attempt = row[0] + 1
    if attempt >= MAX_RETRIES:
        new_status = 'dead'
        outcome = 'dead'
    else:
        new_status = 'failed'
        outcome = 'retry'
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "UPDATE frames SET status=?, node=?, attempts=?, last_error=?, updated_at=datetime('now') WHERE job_id=? AND frame_number=?",
            (new_status, hostname, attempt, message, job_id, frame_number)
        )
        ts = int(time.time())
        db.execute(
            "INSERT INTO error_log(ts, node, job_id, frame_number, attempt, message) VALUES (?,?,?,?,?,?)",
            (ts, hostname, job_id, frame_number, attempt, message)
        )
        db.execute(
            "INSERT INTO retry_log(ts, node, job_id, frame_number, attempt, outcome) VALUES (?,?,?,?,?,?)",
            (ts, hostname, job_id, frame_number, attempt, outcome)
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    print(attempt)

def cmd_attempts(args):
    if not args:
        return
    job_id, frame_number = parse_frame_ref(args[0])
    db = get_db_readonly()
    cur = db.execute("SELECT attempts FROM frames WHERE job_id=? AND frame_number=?", (job_id, frame_number))
    row = cur.fetchone()
    print(row[0] if row else 0)

def cmd_backoff_wait(args):
    if len(args) < 2:
        return
    hostname = args[0]
    job_id, frame_number = parse_frame_ref(args[1])
    db = get_db()
    cur = db.execute("SELECT attempts FROM frames WHERE job_id=? AND frame_number=?", (job_id, frame_number))
    row = cur.fetchone()
    count = row[0] if row else 0
    if count <= 1:
        return
    wait = BACKOFF_BASE * (2 ** (count - 2))
    ts = int(time.time())
    db.execute(
        "INSERT INTO error_log(ts, node, job_id, frame_number, attempt, message) VALUES (?,?,?,?,?,?)",
        (ts, hostname, job_id, frame_number, count, f"backoff={wait}s")
    )
    time.sleep(wait)

def cmd_log_error(args):
    if len(args) < 2:
        return
    hostname = args[0]
    message = ' '.join(args[1:])
    db = get_db()
    db.execute(
        "INSERT INTO error_log(ts, node, job_id, frame_number, attempt, message) VALUES (?,?,?,?,?,?)",
        (int(time.time()), hostname, None, None, 0, message)
    )

def cmd_progress(args):
    db = get_db_readonly()
    now = int(time.time())
    cutoff = now - 10
    cur = db.execute("""
        SELECT node, COUNT(*) as total,
               SUM(CASE WHEN ts > ? THEN 1 ELSE 0 END) as recent
        FROM progress GROUP BY node
    """, (cutoff,))
    result = {}
    for node, total, recent in cur:
        recent = recent or 0
        fph = recent / 10.0 * 3600
        result[node] = {"fph": fph, "total": total}
    print(json.dumps(result))

def cmd_stats_add(args):
    if len(args) < 9:
        return
    ts, node, cpu, mem, disk_r, disk_w, net_rx, net_tx, temp = args[:9]
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "INSERT INTO node_stats(ts, node, cpu, mem, disk_r, disk_w, net_rx, net_tx, temp) VALUES (?,?,?,?,?,?,?,?,?)",
            (int(ts), node, float(cpu), float(mem), int(disk_r), int(disk_w), int(net_rx), int(net_tx), float(temp))
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

def cmd_stats(args):
    db = get_db_readonly()
    cur = db.execute("""
        SELECT node, cpu, mem, disk_r, disk_w, net_rx, net_tx, temp
        FROM node_stats
        WHERE (node, ts) IN (SELECT node, MAX(ts) FROM node_stats GROUP BY node)
    """)
    result = {}
    for row in cur:
        result[row[0]] = {
            "cpu": row[1], "mem": row[2], "disk_r": row[3], "disk_w": row[4],
            "net_rx": row[5], "net_tx": row[6], "temp": row[7]
        }
    print(json.dumps(result))

def cmd_queue_sizes(args):
    db = get_db_readonly()
    pending = db.execute("""
        SELECT COUNT(*) FROM frames f JOIN jobs j ON f.job_id=j.id
        WHERE f.status='pending' AND j.status='active'
    """).fetchone()[0]
    assigned = db.execute("""
        SELECT COUNT(*) FROM frames f JOIN jobs j ON f.job_id=j.id
        WHERE f.status='assigned' AND j.status='active'
    """).fetchone()[0]
    failed = db.execute("""
        SELECT COUNT(*) FROM frames f JOIN jobs j ON f.job_id=j.id
        WHERE f.status='failed' AND j.status='active'
    """).fetchone()[0]
    dead = db.execute("""
        SELECT COUNT(*) FROM frames f JOIN jobs j ON f.job_id=j.id
        WHERE f.status='dead'
    """).fetchone()[0]
    print(json.dumps({"main": pending + assigned, "failed": failed, "dead": dead}))

def cmd_retry_info(args):
    db = get_db_readonly()
    total_retries = db.execute("SELECT COUNT(*) FROM retry_log WHERE outcome='retry'").fetchone()[0]
    total_dead = db.execute("SELECT COUNT(*) FROM retry_log WHERE outcome='dead'").fetchone()[0]
    cur = db.execute("SELECT node, outcome, COUNT(*) FROM retry_log GROUP BY node, outcome")
    by_node = {}
    for node, outcome, count in cur:
        if node not in by_node:
            by_node[node] = {"retries": 0, "dead": 0}
        by_node[node][outcome] = count
    print(json.dumps({"total_retries": total_retries, "total_dead": total_dead, "by_node": by_node}))

def cmd_errors(args):
    n = int(args[0]) if args else 8
    db = get_db_readonly()
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
    print(json.dumps(lines))

def cmd_config(args):
    if not args:
        return
    if len(args) == 1:
        db = get_db_readonly()
        cur = db.execute("SELECT value FROM config WHERE key=?", (args[0],))
        row = cur.fetchone()
        print(row[0] if row else '')
    else:
        db = get_db()
        db.execute("INSERT OR REPLACE INTO config(key, value) VALUES (?, ?)", (args[0], args[1]))

CMDS = {
    'init': cmd_init,
    'job-create': cmd_job_create,
    'job-list': cmd_job_list,
    'current-job': cmd_current_job,
    'job-info': cmd_job_info,
    'frame-info': cmd_frame_info,
    'dequeue': cmd_dequeue,
    'complete': cmd_complete,
    'fail': cmd_fail,
    'attempts': cmd_attempts,
    'backoff-wait': cmd_backoff_wait,
    'log-error': cmd_log_error,
    'progress': cmd_progress,
    'stats-add': cmd_stats_add,
    'stats': cmd_stats,
    'queue-sizes': cmd_queue_sizes,
    'retry-info': cmd_retry_info,
    'errors': cmd_errors,
    'config': cmd_config,
}

WRITE_CMDS = {'init', 'job-create', 'dequeue', 'complete', 'fail', 'backoff-wait', 'log-error', 'stats-add', 'config'}

if __name__ == '__main__':
    signal.signal(signal.SIGALRM, lambda sig, frame: sys.exit(1))
    signal.alarm(20)
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        signal.alarm(0)
        print(f"Usage: {sys.argv[0]} <command> [args]", file=sys.stderr)
        print(f"Commands: {', '.join(sorted(CMDS.keys()))}", file=sys.stderr)
        sys.exit(1)
    cmd = CMDS[sys.argv[1]]
    try:
        if sys.argv[1] in WRITE_CMDS:
            retry_on_lock(cmd, sys.argv[2:])
        else:
            cmd(sys.argv[2:])
    finally:
        signal.alarm(0)
