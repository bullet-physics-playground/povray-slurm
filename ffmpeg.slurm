#!/usr/bin/env bash

#SBATCH --job-name=ffmpeg
#SBATCH --time=01:00:00
#SBATCH --output=logs/ffmpeg.out

JOB_ID=${JOB_ID:-$(python3 db.py current-job | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null)}

[ -z "$JOB_ID" ] && { echo "JOB_ID not set"; exit 1; }

read JID FNAME TFRAMES OUT_DIR JNAME PRIO <<< "$(python3 db.py frame-info "${JOB_ID}:1" 2>/dev/null)"
[ -z "$OUT_DIR" ] && { echo "No output dir for job $JOB_ID"; exit 1; }
[ -d "$OUT_DIR" ] || { echo "Output dir $OUT_DIR not found"; exit 1; }

ffmpeg -y -framerate 60 -color_range 2 -color_trc 13 -color_primaries 1 -i "$OUT_DIR/frame_%04d.png" -c:v libx265 -crf 14 -preset slow -pix_fmt yuv420p10le -vf "format=yuv420p10le" -x265-params "colorprim=9:transfer=16:colormatrix=9:hdr10=1:master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1):max-cll=1000,400" -an "job_${JOB_ID}.mp4"
