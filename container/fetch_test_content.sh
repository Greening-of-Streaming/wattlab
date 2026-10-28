#!/usr/bin/env bash
# Download OWL's open-licence test videos — byte-identical to the files GoS1
# encodes (checksums below), so an encode measured here and one measured on
# GoS1 start from the same input. Served by the public OWL instance's
# "Download Source Video" route. In-house GoS content is never fetched.
#
#   fetch_test_content.sh            the three 2-minute extracts (~1.3 GB)
#   fetch_test_content.sh meridian_120s
set -euo pipefail

BASE=${OWL_CONTENT_BASE:-https://wattlab.greeningofstreaming.org}
DEST=${OWL_DATA_DIR:-/data}/test_content

# key | file name sources.py expects | sha256 | licence
CATALOG="
meridian_120s|meridian_120s.mp4|b8636515e648e3c2ff9b3c3fc8ad1bf53cbbf9116e5f473d02731525ae935075|Netflix Open Content, CC BY 4.0
bbb_120s|bbb_120s.mp4|33016acb2a79d33205cf3fc2cdea6a10aa8c7f2bab3a8740eeb946be192ef3b3|Blender Foundation, CC BY 3.0
kranjska_120s|kranjska_dh_120s.mp4|4b5053123e1cbf7809f9ba028a8003d054482dad1cd81fb8ead9e56f5cf78314|Maks Berc via Wikimedia Commons, CC BY 3.0
"

want=("$@")
mkdir -p "$DEST"
echo "$CATALOG" | while IFS='|' read -r key file sha licence; do
  [ -n "$key" ] || continue
  if [ ${#want[@]} -gt 0 ] && [[ ! " ${want[*]} " =~ " $key " ]]; then continue; fi
  out="$DEST/$file"
  if [ -f "$out" ] && echo "$sha  $out" | sha256sum -c --status; then
    echo "ok    $file (already present)"; continue
  fi
  echo "fetch $file  [$licence]"
  curl -fL --retry 3 -o "$out.part" "$BASE/video/source/$key/download"
  if echo "$sha  $out.part" | sha256sum -c --status; then
    mv "$out.part" "$out"; echo "ok    $file"
  else
    rm -f "$out.part"; echo "FAIL  $file: checksum mismatch" >&2; exit 1
  fi
done
