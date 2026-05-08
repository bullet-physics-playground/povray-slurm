#!/bin/bash

echo "Live Monitoring (Ctrl+C to stop)"
echo

while true; do

  clear

  echo "Time: $(date)"
  echo "======================================"

  python3 db.py job-list 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
if not data:
    print('No jobs.')
    sys.exit(0)
for j in data:
    pct = round(100 * j['completed'] / j['total'], 1) if j['total'] else 0
    print(f\"  #{j['id']}  {j['name']:<28s}  pri={j['priority']}  {j['status']:<10s}  {j['completed']:>4d}/{j['total']:<4d}  {pct:>5.1f}%  fail={j['failed']}  dead={j['dead']}\")
" 2>/dev/null

  echo "======================================"
  echo "-- Queue --"

  python3 db.py queue-sizes 2>/dev/null | python3 -c "
import json, sys
q = json.load(sys.stdin)
print(f'  Pending:   {q.get(\"main\", \"?\")}')
print(f'  Failed:    {q.get(\"failed\", \"?\")}')
print(f'  Dead:      {q.get(\"dead\", \"?\")}')
" 2>/dev/null

  echo "======================================"
  echo "-- Current job --"

  python3 db.py current-job 2>/dev/null | python3 -c "
import json, sys
j = json.load(sys.stdin)
if j:
    pct = round(100 * j['completed'] / j['total_frames'], 1)
    print(f'  {j[\"name\"]}  (job #{j[\"id\"]}, pri={j[\"priority\"]})')
    print(f'  Status: {j[\"status\"]}  |  {j[\"completed\"]}/{j[\"total_frames\"]} ({pct}%)')
    print(f'  Pending: {j[\"pending\"]}  Assigned: {j[\"assigned\"]}  Failed: {j[\"failed\"]}  Dead: {j[\"dead\"]}')
else:
    print('  (none active)')
" 2>/dev/null

  echo "======================================"
  echo "-- Per-node progress --"

  python3 db.py progress 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
total = 0
if data:
    for node, info in sorted(data.items()):
        total += info['total']
        print(f'  {node:<10s}  {info[\"total\"]:>4d} frames  {info[\"fps\"]:>5.2f} fps')
else:
    print('  (no data)')
print(f'  {\"-\"*30}')
print(f'  Total frames rendered: {total}')
" 2>/dev/null

  sleep 2

done
