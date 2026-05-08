# POV-Ray Cluster Rendering

Distributed ray-tracing animation rendering using SLURM work-stealing on a compute cluster.

## Introduction

This project renders POV-Ray animations in parallel across multiple cluster nodes using SLURM array jobs or a dynamic work-stealing worker pool.

- **POV-Ray** - Persistence of Vision Ray Tracer: open-source ray tracing engine for 3D rendering
- **SLURM** - Simple Linux Utility for Resource Management: workload manager for HPC clusters

Each frame is rendered with motion blur by averaging multiple time samples, then encoded to MP4 video.

## Requirements

- SLURM cluster with `sbatch`, `srun`
- POV-Ray (`povray`)
- Python 3 with PIL/Pillow
- FFmpeg
- ImageMagick (`convert`) — for work-stealing worker

## Files

| File | Description |
|------|-------------|
| `benchmark.slurm` | SLURM batch job that iterates over PAR/THREADS combinations, runs a short POV-Ray render for each, and writes the fastest combination to `best_config.txt`. The array job and workers read this file to configure parallelism. |
| `frame.slurm` | SLURM array task that renders a single frame using the array task ID. Calls POV-Ray with `+SF<N> +EF<N>` for single-frame rendering, then averages multiple time samples via ImageMagick `convert` or Python PIL fallback. On failure, calls `handle_failure()` which pushes the frame to `failed_queue.txt` (or `dead_queue.txt` after 3 attempts) and records the failing host in `.retry_hosts/`. Designed to be submitted via `submit_all.sh`. |
| `submit_all.sh` | Full-pipeline orchestrator: runs `generate_queue.sh` to create the frame queue, submits `benchmark.slurm` to find optimal PAR/THREADS, then submits `frame.slurm` as a dependent array job (`--dependency=afterok`). After the array completes, submits `ffmpeg.slurm` to encode the rendered frames to MP4. Accepts optional `FRAMES`, `WIDTH`, `HEIGHT` arguments. |
| `generate_queue.sh` | Reads the total frame count from `.frames`, then writes zero-padded frame IDs (`0001` through `N`) into `frame_queue.txt`, one per line. Used to initialize the queue before work-stealing runs. |
| `ffmpeg.slurm` | Post-processing SLURM job that encodes all rendered PNG frames in `frames/` into an MP4 video using libx264. Runs after the array job completes in the `submit_all.sh` pipeline. |
| `worker_ws.sh` | Work-stealing worker that runs in an infinite loop on a cluster node. Each worker locks `queue.lock` and atomically dequeues frame IDs from the shared `frame_queue.txt`. When the main queue is empty, it falls back to `failed_queue.txt` for retries. Before rendering a retried frame, it checks `.retry_hosts/<frame>` to ensure the frame is NOT re-processed by the same node that failed it — if the host matches, the frame is re-enqueued for another worker. After dequeuing, it renders the frame with POV-Ray across multiple time samples (motion blur), averages them with ImageMagick, and logs success to `progress.log` or calls `handle_failure()`. Also runs a background `stats_collector` that writes CPU%, RAM%, disk I/O, network I/O, and CPU temperature to `node_stats.log` every 5 seconds. |
| `dynamic_ws.slurm` | Launcher that requests 4 nodes via SLURM, then uses `scontrol show hostnames` + `srun -w <node> worker_ws.sh &` to start one worker instance per node in the background. Each worker independently dequeues from the shared queue file (synchronized via `flock` on `queue.lock`). |
| `dashboard_ws.py` | Real-time WebSocket server (Flask-SocketIO + eventlet) that serves the dashboard frontend and runs a background polling loop (`watcher()`). Every second it reads `progress.log` to compute per-node FPS over a 10-second sliding window, parses `node_stats.log` for live resource usage, reads `retry.log` for retry analytics and per-node dead-frame counts, tails `errors.log` for the error feed, and counts queue sizes. Emits a single `update` event with all data to connected browsers. |
| `index_ws.html` | Dashboard frontend with SocketIO client, Chart.js FPS line chart, live stats table with resource bars, interactive resource heatmap (canvas-based, 40-snapshot history, selectable metric), queue status cards, retry analytics table, and a live error log tail. Updates in real time from the WebSocket server. |
| `monitor.sh` | Lightweight terminal-based monitor that reads `progress.log` and displays per-node frame counts and frames-per-second, refreshed every 2 seconds via `watch`. Uses `awk` for log parsing. |
| `scene.pov` | POV-Ray scene description file defining the 3D geometry, camera, lights, and materials for the animation. |
| `animation.ini` | POV-Ray animation configuration template with placeholder values (`WIDTH_VAL`, `HEIGHT_VAL`, `FRAME_COUNT`). The pipeline scripts resolve these to concrete values in `animation_render.ini` before rendering. |
| `best_config.txt` | Output of `benchmark.slurm`. Contains two integers: `PAR THREADS` (e.g., `4 1`). Read by `worker_ws.sh` and `frame.slurm` to configure subprocess parallelism and POV-Ray thread count. |
| `.retry_counts/` | Directory with one file per failed frame (named by zero-padded frame ID, e.g., `0015`). Each file contains a single integer: the current retry attempt count (0, 1, 2, …). Managed by `handle_failure()` in both `worker_ws.sh` and `frame.slurm`. |
| `.retry_hosts/` | Directory with one file per failed frame, containing the hostname of the node that last failed that frame. Used by `worker_ws.sh` to ensure retries are dispatched to a different node than the one that failed. |
| `failed_queue.txt` | Shared queue file containing frame IDs queued for retry. Workers fall back to this queue when the main queue is empty. Garbage-collected incrementally as workers dequeue frames. |
| `dead_queue.txt` | Shared queue file for frames that exceeded `MAX_RETRIES` (default 3). These frames are considered permanently failed and are not re-attempted. |
| `retry.log` | Append-only log with one line per retry or dead event: `<timestamp> <hostname> <frame> <attempt> retry\|dead`. Read by the dashboard for retry analytics. |
| `errors.log` | Append-only detailed error log with per-attempt failure reasons, backoff wait durations, and dead-frame markers: `<timestamp> <hostname> frame=<frame> attempt=<N> failed\|DEAD\|backoff=<N>s\|queued for retry`. |

## Rendering Modes

### Array Mode (SLURM array jobs)

```bash
./submit_all.sh [FRAMES] [WIDTH] [HEIGHT]
```

Submits a benchmark job, then an array job where each SLURM task renders one frame independently. Failed frames are pushed to the retry queue for the work-stealing workers to pick up.

### Work-Stealing Mode (dynamic pool)

```bash
./generate_queue.sh 120
sbatch dynamic_ws.slurm
```

Launches `worker_ws.sh` on 4 nodes. Workers pull frames from a shared queue — faster nodes automatically render more frames. Includes retry logic and system stats collection.

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
| **Error Log** | Live tail of `errors.log` showing failures, backoffs, and dead frames |

## Retry & Dead Queue System

Failed frames are automatically retried with exponential backoff:

1. **First failure** — frame goes to `failed_queue.txt` (retry count = 1)
2. **Retry** — worker applies backoff: `5s × 2^(attempt-2)` before re-rendering
3. **Max retries exceeded** (default 3) — frame moved to `dead_queue.txt`
4. All events are logged to `retry.log` and `errors.log` for debugging

Retry counters are stored in `.retry_counts/` (one file per frame).

## Stats Collection

Each worker runs a background `stats_collector` that every 5 seconds writes to `node_stats.log`:

- CPU usage (%)
- RAM usage (%)
- Disk I/O (bytes/s read/write)
- Network I/O (bytes/s RX/TX)
- CPU temperature (°C)

The dashboard reads this file and displays live per-node resource usage.

## Log Formats

### progress.log
```
<timestamp> <hostname> <frame>
```
```
1776885823 m73 0015
1776885827 t630-4 0016
```

### node_stats.log
```
<timestamp> <hostname> <cpu%> <mem%> <disk_r_bps> <disk_w_bps> <net_rx_bps> <net_tx_bps> <temp_c>
```

### retry.log
```
<timestamp> <hostname> <frame> <attempt> retry|dead
```

### errors.log
```
<timestamp> <hostname> frame=<frame> attempt=<N> failed|DEAD|backoff=<N>s|queued for retry
```

## Manual Video Encoding

```bash
ffmpeg -framerate 30 -i frames/frame_%04d.png \
  -c:v libx264 -pix_fmt yuv420p output.mp4
```

## License

See [LICENSE](LICENSE) file.

## Authors

[Jakob Flierl](https://github.com/koppi) - Comments, bug reports, and pull requests welcome!
