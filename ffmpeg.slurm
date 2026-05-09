#!/usr/bin/env bash

#SBATCH --job-name=pov_ffmpeg
#SBATCH --time=00:10:00
#SBATCH --output=logs/ffmpeg.out
#SBATCH --nodes=1

JOB_ID=${JOB_ID:-$(python3 db.py current-job | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null)}

[ -z "$JOB_ID" ] && { echo "JOB_ID not set"; exit 1; }

read JID FNAME TFRAMES OUT_DIR JNAME PRIO <<< "$(python3 db.py frame-info "${JOB_ID}:1" 2>/dev/null)"
[ -z "$OUT_DIR" ] && { echo "No output dir for job $JOB_ID"; exit 1; }
[ -d "$OUT_DIR" ] || { echo "Output dir $OUT_DIR not found"; exit 1; }

ffmpeg -y -framerate 30 -i "$OUT_DIR/frame_%04d.png" -c:v libx264 -pix_fmt yuv420p "job_${JOB_ID}.mp4"
