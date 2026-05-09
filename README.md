# POV-Ray Cluster Rendering

Distributed ray-tracing animation rendering using SLURM work-stealing on a compute cluster.

## Introduction

This project renders POV-Ray animations in parallel across multiple cluster nodes using SLURM array jobs or a dynamic work-stealing worker pool.

- **POV-Ray** - Persistence of Vision Ray Tracer: open-source ray tracing engine for 3D rendering
- **SLURM** - Simple Linux Utility for Resource Management: workload manager for HPC clusters

Each frame is rendered with motion blur by averaging multiple time samples, then encoded to MP4 video.

## Requirements

- SLURM cluster with `sbatch`, `srun`
- POV-Ray 3.8 (`povray`) — version 3.7 will **not** work
- Python 3 with PIL/Pillow and `sqlite3` (stdlib)
- FFmpeg
- ImageMagick (`convert`) — for work-stealing worker

## Files

| File | Description |
|------|-------------|
| `db.py` | Central SQLite database helper. Provides CLI subcommands (`init`, `dequeue`, `complete`, `fail`, `backoff-wait`, `stats-add`, `progress`, `stats`, `queue-sizes`, `retry-info`, `errors`, `config`) used by all pipeline scripts. All data is stored in `render.db`. |
| `benchmark.slurm` | SLURM batch job that iterates over PAR/THREADS combinations, runs a short POV-Ray render for each, and writes the fastest combination to `render.db` via `db.py config`. The array job and workers read config from the database. |
| `frame.slurm` | SLURM array task that renders a single frame using the array task ID. Calls POV-Ray with `+SF<N> +EF<N>` for single-frame rendering, then averages multiple time samples via Python PIL. On failure calls `db.py fail` which updates the frame's retry count and status. Designed to be submitted via `submit_all.sh`. |
| `submit_all.sh` | Full-pipeline orchestrator: runs `db.py init` to create the database, submits `benchmark.slurm` to find optimal PAR/THREADS, then submits `frame.slurm` as a dependent array job (`--dependency=afterok`). After the array completes, submits `ffmpeg.slurm` to encode the rendered frames to MP4. Accepts optional `FRAMES`, `WIDTH`, `HEIGHT` arguments. |
| `ffmpeg.slurm` | Post-processing SLURM job that encodes all rendered PNG frames in `frames/` into an MP4 video using libx264. Runs after the array job completes in the `submit_all.sh` pipeline. |
| `dashboard_ws.py` | Real-time WebSocket server (Flask-SocketIO + eventlet) that serves the dashboard frontend and runs a background polling loop. Every second it queries `render.db` via `db.py` subcommands to get per-node FPS, live resource usage, retry analytics, queue sizes, and error log entries. Emits a single `update` event with all data to connected browsers. |
| `index_ws.html` | Dashboard frontend with SocketIO client, Chart.js FPS line chart, live stats table with resource bars, interactive resource heatmap (canvas-based, 40-snapshot history, selectable metric), queue status cards, retry analytics table, and a live error log tail. Updates in real time from the WebSocket server. |
| `monitor.sh` | Lightweight terminal-based monitor that queries `render.db` directly via `sqlite3` CLI and displays per-node frame counts and frames-per-second, refreshed every 2 seconds. |
| `scene.pov` | POV-Ray scene description file defining the 3D geometry, camera, lights, and materials for the animation. |
| `sphere.pov` | Simple POV-Ray test scene with a moving sphere and plane. |
| `asy1.pov` | Molecular visualization scene exported from VMD. |
| `animation.ini` | POV-Ray animation configuration template with placeholder values (`WIDTH_VAL`, `HEIGHT_VAL`, `FRAME_COUNT`). The pipeline scripts resolve these to concrete values in `animation_render.ini` before rendering. |

## Database Schema (`render.db`)

All pipeline data is stored in a single SQLite database with WAL mode for concurrent access:

| Table | Purpose |
|-------|---------|
| `frames` | One row per frame. Tracks status (`pending`, `assigned`, `completed`, `failed`, `dead`), owning node, retry count, and error message. Replaces `frame_queue.txt`, `failed_queue.txt`, `dead_queue.txt`, `.retry_counts/`, and `.retry_hosts/`. |
| `progress` | Append-only render completion log with timestamp, node, and frame ID. Replaces `progress.log`. |
| `node_stats` | Per-node system stats (CPU%, RAM%, disk I/O, network I/O, temperature) collected every 5 seconds. Replaces `node_stats.log`. |
| `error_log` | Detailed error log with timestamps, frame IDs, attempt numbers, and error messages. Replaces `errors.log`. |
| `retry_log` | Retry/dead event log for analytics. Replaces `retry.log`. |
| `config` | Key-value configuration store (`par`, `threads`, `total_frames`). Replaces `best_config.txt` and `.frames`. |

## Rendering Modes

### Array Mode (SLURM array jobs)

```bash
./submit_all.sh [FRAMES] [WIDTH] [HEIGHT]
```

Submits a benchmark job, then an array job where each SLURM task renders one frame independently. Failed frames are set to `failed` status in the database for the work-stealing workers to retry.

## Realtime Dashboard

```bash
pip install flask flask-socketio eventlet
python dashboard_ws.py   # Open http://localhost:5000
```

### Dashboard Features

| Feature | Description |
|---------|-------------|
| **FPS Chart** | Live line chart of frames per second per node (last 30s) |
| **Node Resources** | CPU%, RAM%, Disk R/W, Net RX/TX, CPU temperature per node |
| **Resource Heatmap** | Grid of nodes × time colored by selected metric (CPU, RAM, FPS, Disk, Net, Temp) |
| **Queue Status** | Active queue, failed queue, dead queue sizes with retry/dead counters |
| **Retry Analytics** | Per-node retry and dead frame counts with row highlighting |
| **Error Log** | Live tail of error log showing failures, backoffs, and dead frames |

## Retry & Dead Queue System

Failed frames are automatically retried with exponential backoff:

1. **First failure** — frame status set to `failed`, attempt count = 1
2. **Retry** — worker applies backoff: `5s × 2^(attempt-2)` before re-rendering
3. **Same-host prevention** — a frame failed by node A will only be retried by a different node
4. **Max retries exceeded** (default 3) — frame status set to `dead`
5. All events are logged to `error_log` and `retry_log` tables

Retry attempt counts are stored in the `frames.attempts` column.

## Stats Collection

Each worker runs a background `stats_collector` that every 5 seconds writes to `node_stats` table via `db.py stats-add`:

- CPU usage (%)
- RAM usage (%)
- Disk I/O (bytes/s read/write)
- Network I/O (bytes/s RX/TX)
- CPU temperature (°C)

The dashboard queries this table and displays live per-node resource usage.

## Concurrency

- **Atomic dequeue**: `db.py dequeue` uses `BEGIN IMMEDIATE` + SELECT + UPDATE inside a single transaction, eliminating the need for `flock`-based file locking.
- **WAL mode**: SQLite Write-Ahead Logging allows concurrent readers and a single writer without blocking.
- **Busy timeout**: Set to 5 seconds to retry automatically on contention.

## License

See [LICENSE](LICENSE) file.

## Authors

[Jakob Flierl](https://github.com/koppi) - Comments, bug reports, and pull requests welcome!
