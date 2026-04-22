#!/usr/bin/env bash

#SBATCH --job-name=pov_ffmpeg
#SBATCH --time=00:10:00
#SBATCH --output=logs/ffmpeg.out
#SBATCH --nodes=1

ffmpeg -y -framerate 30 -i frames/frame_%04d.png -c:v libx264 -pix_fmt yuv420p output.mp4
