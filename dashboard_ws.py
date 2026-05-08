from flask import Flask, send_from_directory
from flask_socketio import SocketIO
import time
import os
from collections import defaultdict

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

LOG_FILE = "progress.log"
STATS_FILE = "node_stats.log"
RETRY_LOG = "retry.log"
ERROR_LOG = "errors.log"
QUEUE_FILE = "frame_queue.txt"
FAILED_QUEUE_FILE = "failed_queue.txt"
DEAD_QUEUE_FILE = "dead_queue.txt"

def parse_log():
    data = defaultdict(list)
    try:
        with open(LOG_FILE) as f:
            for line in f:
                t, node, frame = line.strip().split()
                t = int(t)
                data[node].append(t)
    except (FileNotFoundError, ValueError):
        return {}

    now = int(time.time())
    result = {}

    for node, times in data.items():
        times.sort()
        recent = [t for t in times if now - t <= 10]
        fps = len(recent) / 10.0

        result[node] = {
            "fps": round(fps, 2),
            "total": len(times)
        }

    return result

def parse_stats():
    data = {}
    try:
        with open(STATS_FILE) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 9:
                    host = parts[1]
                    data[host] = {
                        "cpu": float(parts[2]),
                        "mem": float(parts[3]),
                        "disk_r": int(parts[4]),
                        "disk_w": int(parts[5]),
                        "net_rx": int(parts[6]),
                        "net_tx": int(parts[7]),
                        "temp": float(parts[8]),
                    }
    except (FileNotFoundError, OSError):
        return {}
    return data

def parse_retry_log():
    retries = defaultdict(int)
    dead = defaultdict(int)
    by_node = defaultdict(lambda: {"retries": 0, "dead": 0})
    try:
        with open(RETRY_LOG) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 5:
                    node = parts[1]
                    frame = parts[2]
                    outcome = parts[4]
                    if outcome == "dead":
                        dead[frame] += 1
                        by_node[node]["dead"] += 1
                    else:
                        retries[frame] += 1
                        by_node[node]["retries"] += 1
    except (FileNotFoundError, OSError):
        pass
    return {
        "total_retries": sum(retries.values()),
        "total_dead": sum(dead.values()),
        "by_node": dict(by_node),
    }

def tail_errors(n=5):
    try:
        with open(ERROR_LOG) as f:
            lines = f.readlines()
        return [l.strip() for l in lines[-n:]]
    except (FileNotFoundError, OSError):
        return []

def queue_size(path):
    try:
        with open(path) as f:
            return sum(1 for _ in f)
    except (FileNotFoundError, OSError):
        return 0

def watcher():
    last_sizes = {LOG_FILE: 0, STATS_FILE: 0, RETRY_LOG: 0, ERROR_LOG: 0,
                  QUEUE_FILE: 0, FAILED_QUEUE_FILE: 0, DEAD_QUEUE_FILE: 0}
    while True:
        changed = False
        for fname in last_sizes:
            if os.path.exists(fname):
                size = os.path.getsize(fname)
                if size != last_sizes[fname]:
                    last_sizes[fname] = size
                    changed = True
        if changed:
            data = parse_log()
            stats = parse_stats()
            for node in data:
                if node in stats:
                    data[node]["stats"] = stats[node]

            retry_info = parse_retry_log()
            for node, r in retry_info["by_node"].items():
                if node in data:
                    data[node]["retries"] = r["retries"]
                    data[node]["dead"] = r["dead"]

            data["_queues"] = {
                "main": queue_size(QUEUE_FILE),
                "failed": queue_size(FAILED_QUEUE_FILE),
                "dead": queue_size(DEAD_QUEUE_FILE),
            }
            data["_retry"] = {
                "total_retries": retry_info["total_retries"],
                "total_dead": retry_info["total_dead"],
            }
            data["_errors"] = tail_errors(8)

            socketio.emit("update", data)
        socketio.sleep(1)

@app.route("/")
def index():
    return send_from_directory(".", "index_ws.html")

if __name__ == "__main__":
    socketio.start_background_task(watcher)
    socketio.run(app, host="0.0.0.0", port=5000)
