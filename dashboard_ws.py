from flask import Flask, send_from_directory
from flask_socketio import SocketIO
import time
import os
from collections import defaultdict

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

LOG_FILE = "progress.log"

def parse_log():
    data = defaultdict(list)
    try:
        with open(LOG_FILE) as f:
            for line in f:
                t, node, frame = line.strip().split()
                t = int(t)
                data[node].append(t)
    except FileNotFoundError:
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

def watcher():
    last_size = 0
    while True:
        if os.path.exists(LOG_FILE):
            size = os.path.getsize(LOG_FILE)
            if size != last_size:
                last_size = size
                data = parse_log()
                socketio.emit("update", data)
        socketio.sleep(1)

@app.route("/")
def index():
    return send_from_directory(".", "index_ws.html")

if __name__ == "__main__":
    socketio.start_background_task(watcher)
    socketio.run(app, host="0.0.0.0", port=5000)
