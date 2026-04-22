#!/usr/bin/env bash

#SBATCH --job-name=pov_frame
#SBATCH --time=00:05:00
#SBATCH --output=logs/frame_%A_%a.out
#SBATCH --array=1-FRAMES
#SBATCH --nodes=1
#SBATCH --cpus-per-task=4

INI_FILE="animation_render.ini"
FRAME_DIR="frames"
SAMPLES=6

read PAR THREADS < best_config.txt
read FRAMES < .frames

FRAME=$SLURM_ARRAY_TASK_ID
NUM=$FRAME

mkdir -p "$FRAME_DIR"

TMP="/tmp/frame_${NUM}_$$"
mkdir -p "$TMP"

START=$(awk "BEGIN {print ($NUM-1)/$FRAMES}")
END=$(awk "BEGIN {print $NUM/$FRAMES}")
DELTA=$(awk "BEGIN {print ($END-$START)/$SAMPLES}")

pids=()
for ((i=0;i<SAMPLES;i++)); do
  CLOCK=$(awk "BEGIN {print $START + $i*$DELTA}")
  povray "$INI_FILE" -V +SF$NUM +EF$NUM +KI$CLOCK +KF$CLOCK -WT$THREADS -D +O"$TMP/sub_$i.png" &
  pids+=($!)
done
wait

python3 -c "
from PIL import Image
import glob
imgs = [Image.open(f) for f in sorted(glob.glob('$TMP/sub_*.png'))]
img = Image.new('RGB', imgs[0].size)
px_in = [i.get_flattened_data() for i in imgs]
px_out = []
for y in range(imgs[0].size[1]):
    for x in range(imgs[0].size[0]):
        i = y * imgs[0].size[0] + x
        r = sum(p[i][0] for p in px_in) // len(imgs)
        g = sum(p[i][1] for p in px_in) // len(imgs)
        b = sum(p[i][2] for p in px_in) // len(imgs)
        px_out.append((r, g, b))
img.putdata(px_out)
img.save('$FRAME_DIR/frame_$(printf "%04d" $FRAME).png')
"
rm -rf "$TMP"

echo "$(date +%s) $(hostname) $(printf "%04d" $FRAME)" >> progress.log
