# POV-Ray Cluster Rendering

Distributed ray-tracing animation rendering using SLURM work-stealing on a compute cluster.

## Introduction

This project renders POV-Ray animations in parallel across multiple cluster nodes using SLURM array jobs.

- **POV-Ray** - Persistence of Vision Ray Tracer: open-source ray tracing engine for 3D rendering
- **SLURM** - Simple Linux Utility for Resource Management: workload manager for HPC clusters

Each frame is rendered with motion blur by averaging multiple time samples, then encoded to MP4 video.

## Requirements

- SLURM cluster with `sbatch`, `srun`
- POV-Ray (`povray`)
- Python 3 with PIL/Pillow
- FFmpeg

## Files

| File | Description |
|------|-------------|
| `benchmark.slurm` | Finds optimal PAR/THREADS settings |
| `frame.slurm` | Renders single frame (SLURM array) |
| `submit_all.sh` | Orchestrates the full pipeline |
| `generate_queue.sh` | Generates frame queue |
| `ffmpeg.slurm` | Converts PNG frames to MP4 video |
| `dashboard_ws.py` | Realtime progress WebSocket dashboard |
| `scene.pov` | POV-Ray scene file |
| `animation.ini` | Animation template |
| `best_config.txt` | Best parallelism settings |
| `frame_queue.txt` | Pending frame numbers |
| `progress.log` | Render progress log |
| `frames/` | Rendered PNG frames |

## Pipeline

1. **benchmark** - Tests PAR=1,2,4,... THREADS combinations
2. **frame** (array) - Each frame renders with motion blur averaging
3. **ffmpeg** - Encodes PNG frames to MP4 video

## Output

- `frames/frame_XXXX.png` - 120 rendered frames
- `output.mp4` - Final video (30 fps)

## Manual Video Encoding

```bash
ffmpeg -framerate 30 -i frames/frame_%04d.png \
  -c:v libx264 -pix_fmt yuv420p output.mp4
```

## Realtime Dashboard

```bash
pip install flask flask-socketio eventlet
python dashboard_ws.py # Open http://localhost:5000
```

## Progress Log Format

```
<timestamp> <hostname> <frame>
```

Example:
```
1776885823 m73 0015
1776885827 t630-4 0016
1776885827 t630-1 0017
```

## License

See [LICENSE](LICENSE) file.

## Authors

[Jakob Flierl](https://github.com/koppi) - Comments, bug reports, and pull requests welcome!
