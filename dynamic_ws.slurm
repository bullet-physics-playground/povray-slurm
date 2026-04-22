#!/usr/bin/env bash

#SBATCH --job-name=pov_ws
#SBATCH --time=01:00:00
#SBATCH --output=logs/ws.out
#SBATCH --nodes=4

for node in $(scontrol show hostnames); do
  echo "Launching worker on $node"
  srun -w "$node" ./worker_ws.sh &
done

wait
