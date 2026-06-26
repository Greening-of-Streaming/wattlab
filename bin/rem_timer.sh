#!/bin/bash
# rem_timer.sh — OWL ↔ Simon timer adapter for /prepare-rem.
#
# OWL's rem_prep.generate_timer_segment() invokes the configured
# `rem_timer_script_path` as:   rem_timer.sh <out> <w> <h> <fps> <dur>
# and then RE-ENCODES the result to the deliverable's codec/bitrate/params so it
# concatenates with the rest of the REM file. So this script only has to produce
# the correct PICTURE at <w>x<h>, <fps>, <dur> seconds, written to <out>.
#
# It reproduces Simon's buildTimer.sh look: black frame, centred MM:SS COUNT-DOWN
# (FreeSerif), GoS logo overlaid top-left. SDR 8-bit for now — OWL's REM encode
# path is SDR-only; HDR/PQ is a planned migration (see rem_prep.py header note).
set -euo pipefail

out="$1"; w="$2"; h="$3"; fps="$4"; dur="$5"

# Assets (override via env if they move). FreeSerif = Simon's font
# (apt: fonts-freefont-ttf); logo lives with Simon's REM toolkit on /srv/data.
font="${REM_TIMER_FONT:-/usr/share/fonts/truetype/freefont/FreeSerif.ttf}"
logo="${REM_TIMER_LOGO:-/srv/data/rem/scripts/GoS.logo.bb.png}"

# Font size tracks Simon's 200px-at-1080p so it scales with resolution.
fs=$(( h * 200 / 1080 ))
if [ "$fs" -lt 24 ]; then fs=24; fi
# Fall back to an always-present font if FreeSerif isn't installed.
[ -f "$font" ] || font="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# Centred MM:SS counting DOWN from <dur> to 0 (Simon's exact expression).
draw="drawtext=fontfile=${font}:fontcolor=white:fontsize=${fs}:text='%{eif\:(${dur}-t)/60\:d\:1}\:%{eif\:mod(${dur}-t, 60)\:d\:2}':x=(w-text_w)/2:y=(h-text_h)/2"
src="color=black:s=${w}x${h}:duration=${dur}:rate=${fps},format=rgb24,${draw}"

# High-quality intermediate (OWL re-encodes to the deliverable afterwards).
enc=(-an -t "${dur}" -c:v libx264 -preset veryfast -crf 12 -pix_fmt yuv420p)

if [ -f "$logo" ]; then
  ffmpeg -hide_banner -y -f lavfi -i "$src" -i "$logo" \
    -filter_complex "[0:v][1:v]overlay=25:25[v]" -map "[v]" "${enc[@]}" "$out"
else
  ffmpeg -hide_banner -y -f lavfi -i "$src" "${enc[@]}" "$out"
fi
