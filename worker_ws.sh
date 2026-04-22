#!/usr/bin/env bash

QUEUE="frame_queue.txt"
LOCK="queue.lock"
LOG_FILE="progress.log"

INI_FILE="animation_render.ini"
FRAME_DIR="frames"
SAMPLES=6

read PAR THREADS < best_config.txt
read FRAMES < .frames

mkdir -p "$FRAME_DIR"

while true; do
  exec 9>$LOCK
  flock -x 9

  FRAME=$(head -n 1 $QUEUE)
  [ -z "$FRAME" ] && flock -u 9 && break

  sed -i '1d' $QUEUE
  flock -u 9

  NUM=$(echo $FRAME | sed 's/^0*//')
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

    if (( ${#pids[@]} >= PAR )); then
      wait -n
    fi
  done
  wait

  echo "$(date +%s) $(hostname) $FRAME" >> $LOG_FILE

  convert "$TMP"/sub_*.png -evaluate-sequence mean "$FRAME_DIR/frame_$FRAME.png"
  rm -rf "$TMP"

done
