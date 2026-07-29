#!/usr/bin/env bash
# Detached overnight queue — runs with or without a live Claude session.
# 1) Pi 5: h264_rt n=2 repeat (Lab-A is free now)
# 2) waits for the Pi 400 matrix to finish, then Pi 400 realtime hevc/av1 arms
# All output appended to results/overnight_queue.log; bench.py checkpoints per row.
cd /srv/data/owl/decode-bench
LOG=results/overnight_queue.log
say(){ echo "[$(date +%H:%M:%S)] $*" >> "$LOG"; }

say "=== overnight queue start ==="

say "job 1: pi5_rt_v2 (h264 rt repeat)"
python3 bench.py pi5_rt_v2.json >> "$LOG" 2>&1
say "job 1 done"

# wait for the pi4 matrix (its own process) to finish before using Lab-B / the Pi 400
while pgrep -f 'bench.py pi4_matrix' >/dev/null; do sleep 30; done
say "pi4_matrix finished — starting job 2: pi4_rt2 (hevc/av1 rt)"
python3 bench.py pi4_rt2.json >> "$LOG" 2>&1
say "job 2 done"

say "=== overnight queue complete — all data on disk, report pending analysis ==="
