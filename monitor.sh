#!/bin/bash

LOG="progress.log"

echo "Live Monitoring (Ctrl+C zum Beenden)"
echo

while true; do

  clear

  if [ ! -f "$LOG" ]; then
    echo "Waiting for data..."
    sleep 2
    continue
  fi

  NOW=$(date +%s)

  echo "Time: $(date)"
  echo "--------------------------------------"

  awk -v now="$NOW" '
  {
    node=$2
    time=$1

    count[node]++
    last[node]=time
    first[node]=(first[node]=="" ? time : first[node])
  }
  END {
    for (n in count) {
      duration = last[n] - first[n]
      fps = (duration > 0) ? count[n]/duration : 0

      printf "%-15s Frames: %-5d FPS: %.2f\n", n, count[n], fps
    }
  }
  ' "$LOG"

  echo "--------------------------------------"
  TOTAL=$(wc -l < "$LOG")
  echo "Total frames done: $TOTAL"

  sleep 2

done
