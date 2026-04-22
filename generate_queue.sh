#!/usr/bin/env bash

FRAMES=${1:-120}
> frame_queue.txt
for ((f=1; f<=FRAMES; f++)); do
  printf "%04d\n" "$f" >> frame_queue.txt
done
echo "Queue created: $FRAMES frames"
