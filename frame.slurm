#!/usr/bin/env bash

#SBATCH --job-name=pov_frame
#SBATCH --time=00:05:00
#SBATCH --output=logs/frame_%A_%a.out
#SBATCH --array=1-FRAMES
#SBATCH --nodes=1
#SBATCH --cpus-per-task=4

INI_FILE="animation_render.ini"
SAMPLES=6
BACKOFF_BASE=5

mkdir -p "$HOME/.povray/3.8"
[ -f "$HOME/.povray/3.8/povray.conf" ] || cat > "$HOME/.povray/3.8/povray.conf" << 'EOF'
[File I/O Security]
none
[Shellout Security]
allowed
EOF

PAR=$(python3 db.py config par)
THREADS=$(python3 db.py config threads)

JOB_ID=${JOB_ID:-1}
FRAME_NUM=$SLURM_ARRAY_TASK_ID
FRAME_REF="${JOB_ID}:${FRAME_NUM}"

read JOB_ID2 FRAME_NUM2 TOTAL_FRAMES OUT_DIR JOB_NAME PRIORITY <<< "$(python3 db.py frame-info "$FRAME_REF")"
mkdir -p "$OUT_DIR"

stats_collector() {
  local host=$(hostname)
  local prev_idle=0 prev_total=0 prev_disk_r=0 prev_disk_w=0 prev_net_rx=0 prev_net_tx=0
  while true; do
    sleep 5
    local cpu=$(grep '^cpu ' /proc/stat)
    local idle=$(awk '{print $5}' <<< "$cpu")
    local total=0
    for v in $(awk '{for(i=2;i<=NF;i++) print $i}' <<< "$cpu"); do
      total=$((total + v))
    done
    local mem_total=$(awk '/MemTotal/{print $2}' /proc/meminfo)
    local mem_avail=$(awk '/MemAvailable/{print $2}' /proc/meminfo)
    local mem_used=$((mem_total - mem_avail))
    local disk=$(awk '$3!~/loop|ram/ && $6>0 {print $3; exit}' /proc/diskstats 2>/dev/null)
    [ -z "$disk" ] && disk=$(lsblk -ndo NAME 2>/dev/null | grep -v loop | grep -v ram | head -1)
    local disk_r=0 disk_w=0
    if [ -n "$disk" ]; then
      disk_r=$(awk -v d="$disk" '$3==d{print $6}' /proc/diskstats 2>/dev/null || echo 0)
      disk_w=$(awk -v d="$disk" '$3==d{print $10}' /proc/diskstats 2>/dev/null || echo 0)
    fi
    local iface=$(ip -o route get 1.1.1.1 2>/dev/null | awk '{print $5}')
    local net_rx=0 net_tx=0
    if [ -n "$iface" ]; then
      net_rx=$(awk -v i="$iface:" '$1==i{print $2}' /proc/net/dev 2>/dev/null || echo 0)
      net_tx=$(awk -v i="$iface:" '$1==i{print $10}' /proc/net/dev 2>/dev/null || echo 0)
    fi
    local temp=0
    for z in /sys/class/thermal/thermal_zone*; do
      local ttype=$(cat "$z/type" 2>/dev/null)
      case "$ttype" in
        x86_pkg_temp|coretemp|cpu-thermal|cpu_thermal|*cpu*|*pkg*)
          temp=$(awk '{printf "%.1f", $1/1000}' "$z/temp" 2>/dev/null)
          break
          ;;
      esac
    done
    [ "$temp" = "0" ] && temp=$(awk '{printf "%.1f", $1/1000}' /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo "0")

    if [ "$prev_total" -ne 0 ]; then
      local cpu_delta=$((total - prev_total))
      local idle_delta=$((idle - prev_idle))
      local cpu_pct=$(awk "BEGIN {printf \"%.1f\", (($cpu_delta-$idle_delta)/$cpu_delta)*100}")
      local mem_pct=$(awk "BEGIN {printf \"%.1f\", ($mem_used/$mem_total)*100}")
      local disk_r_rate=$(( (disk_r - prev_disk_r) * 512 / 5 ))
      local disk_w_rate=$(( (disk_w - prev_disk_w) * 512 / 5 ))
      local net_rx_rate=$(( (net_rx - prev_net_rx) / 5 ))
      local net_tx_rate=$(( (net_tx - prev_net_tx) / 5 ))
      python3 db.py stats-add "$(date +%s)" "$host" "$cpu_pct" "$mem_pct" "$disk_r_rate" "$disk_w_rate" "$net_rx_rate" "$net_tx_rate" "$temp"
    fi
    prev_idle=$idle
    prev_total=$total
    prev_disk_r=$disk_r
    prev_disk_w=$disk_w
    prev_net_rx=$net_rx
    prev_net_tx=$net_tx
  done
}

stats_collector & STATS_PID=$!

TMP="/tmp/frame_${JOB_ID}_${FRAME_NUM}_$$"
mkdir -p "$TMP"

START=$(awk "BEGIN {print ($FRAME_NUM-1)/$TOTAL_FRAMES}")
END=$(awk "BEGIN {print $FRAME_NUM/$TOTAL_FRAMES}")
DELTA=$(awk "BEGIN {print ($END-$START)/$SAMPLES}")

pids=()
fail=0
for ((i=0;i<SAMPLES;i++)); do
  CLOCK=$(awk "BEGIN {print $START + $i*$DELTA}")
  povray "$INI_FILE" -CC +SF$FRAME_NUM +EF$FRAME_NUM +KI$CLOCK +KF$CLOCK -WT$THREADS -D +O"$TMP/sub_$i.png" &
  pids+=($!)
done
for pid in "${pids[@]}"; do
  wait $pid || fail=1
done

if [ $fail -eq 0 ]; then
  FRAME_PAD=$(printf "%04d" "$FRAME_NUM")
  python3 -c "
from PIL import Image
import glob
imgs = [Image.open(f) for f in sorted(glob.glob('$TMP/sub_*.png'))]
if not imgs:
    exit(1)
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
img.save('$OUT_DIR/frame_$FRAME_PAD.png')
" || fail=1
fi

rm -rf "$TMP"
kill $STATS_PID 2>/dev/null

if [ $fail -eq 0 ]; then
  python3 db.py complete "$FRAME_REF" "$(hostname)"
else
  python3 db.py fail "$FRAME_REF" "$(hostname)" "povray_exit=$fail"
fi
