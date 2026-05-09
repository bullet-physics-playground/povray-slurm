#!/usr/bin/env bash

#SBATCH --job-name=pov_bench
#SBATCH --cpus-per-task=4
#SBATCH --time=00:20:00
#SBATCH --output=logs/bench.out

INI_FILE="animation.ini"
FRAME=20
TMP_DIR="/tmp/pov_bench_$SLURM_JOB_ID"
SAMPLES=6
TOTAL_CPUS=$SLURM_CPUS_PER_TASK

mkdir -p "$HOME/.povray/3.8"
[ -f "$HOME/.povray/3.8/povray.conf" ] || cat > "$HOME/.povray/3.8/povray.conf" << 'EOF'
[File I/O Security]
none
[Shellout Security]
allowed
EOF

mkdir -p "$TMP_DIR" logs

BEST_TIME=999999
BEST=""

for PAR in 1 2 4 8 16 32 64 128; do
  (( PAR > TOTAL_CPUS )) && continue
  THREADS=$((TOTAL_CPUS / PAR))

  START=$(date +%s.%N)

  pids=()
  for ((i=0;i<SAMPLES;i++)); do
    CLOCK=$(awk "BEGIN {print ($FRAME-1)/120 + $i*(1.0/120/$SAMPLES)}")
    povray "$INI_FILE" -CC +SF$FRAME +EF$FRAME +KI$CLOCK +KF$CLOCK -WT$THREADS -D +O"$TMP_DIR/test_$i.png" &
    pids+=($!)

    if (( ${#pids[@]} >= PAR )); then
      wait -n
    fi
  done
  wait

  END=$(date +%s.%N)
  TIME=$(awk "BEGIN {print $END - $START}")

  if echo "$TIME $BEST_TIME" | awk '{exit !($1 < $2)}'; then
    BEST_TIME=$TIME
    BEST="$PAR $THREADS"
  fi

  rm -f "$TMP_DIR"/*.png
done

python3 db.py config par $(echo $BEST | awk '{print $1}')
python3 db.py config threads $(echo $BEST | awk '{print $2}')
echo "Best config: $BEST"
