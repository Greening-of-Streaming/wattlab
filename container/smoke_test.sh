#!/usr/bin/env bash
# End-to-end smoke test of a running OWL container (synthetic or real power).
# Run on the Docker host:  container/smoke_test.sh [base_url]   (default http://127.0.0.1:8000)
# Checks: service up · power source stamped · Lab/Anonymous tiers · one CPU video
# encode and one tier-S LLM job complete with a confidence flag and stored result.
set -uo pipefail

BASE=${1:-http://127.0.0.1:8000}
COMPOSE=${COMPOSE:-docker compose -f "$(dirname "$0")/docker-compose.yml"}
pass=0; fail=0
ok()   { echo "PASS  $*"; pass=$((pass+1)); }
bad()  { echo "FAIL  $*"; fail=$((fail+1)); }
jget() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval('d'+sys.argv[1]))" "$1" 2>/dev/null; }

wait_job() {   # $1 type (video|llm) $2 job id → prints final status json; up to $3 seconds
  local typ=$1 id=$2 deadline=$((SECONDS + ${3:-1800})) st
  while [ $SECONDS -lt $deadline ]; do
    st=$(curl -fsS "$BASE/$typ/job/$id" 2>/dev/null)
    case "$(echo "$st" | jget "['status']")" in
      done)  echo "$st"; return 0 ;;
      error) echo "$st"; return 1 ;;
    esac
    sleep 10
  done
  echo '{"status":"timeout"}'; return 1
}

# 1. up
live=$(curl -fsS "$BASE/live") && ok "/live: $live" || { bad "/live unreachable at $BASE"; exit 1; }

# 2. power source + banner
page=$(curl -fsS "$BASE/video")
if echo "$page" | grep -q "SIMULATED POWER"; then ok "simulated-power banner shown"
elif echo "$page" | grep -q "Power source unavailable"; then bad "power source unavailable (see banner on /video)"
else ok "real power source (no simulated banner)"; fi

# 3. tiers: the host itself is Lab (loopback / Docker bridge in OWL_LAB_CIDRS).
#    Anonymous is checked from outside (OUTSIDE_URL) — from here every request is Lab.
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/audience")
[ "$code" = 200 ] && ok "Lab-only /audience reachable from host" || bad "/audience from host → $code"
if [ -n "${OUTSIDE_URL:-}" ]; then   # set to the public URL to test from a non-Lab vantage point
  code=$(curl -s -o /dev/null -w '%{http_code}' "$OUTSIDE_URL/audience")
  case "$code" in 401|403|404) ok "outside visitor refused Lab page ($code)" ;; *) bad "outside /audience → $code (outside is Lab?!)" ;; esac
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$OUTSIDE_URL/settings")
  case "$code" in 401|403|404) ok "outside visitor refused settings write ($code)" ;; *) bad "outside POST /settings → $code" ;; esac
fi

# 4. CPU video encode (H.264 CPU on the Meridian 2-min extract)
r=$(curl -fsS -X POST "$BASE/video/use-source" -F source_key=meridian_120s -F preset=cpu -F compute_vmaf=false)
id=$(echo "$r" | jget "['job_id']")
if [ -n "$id" ]; then
  st=$(wait_job video "$id" 3600); flag=$(echo "$st" | grep -o '🟢\|🟡\|🔴' | head -1)
  [ -n "$flag" ] && ok "video job $id done, flag $flag" || bad "video job $id: $(echo "$st" | head -c 300)"
else bad "video enqueue: $r"; fi

# 5. tier-S LLM job
r=$(curl -fsS -X POST "$BASE/llm/run" -F model_key=qwen3.5:4b -F task_key=T1 -F device=cpu)
id=$(echo "$r" | jget "['job_id']")
if [ -n "$id" ]; then
  st=$(wait_job llm "$id" 3600); flag=$(echo "$st" | grep -o '🟢\|🟡\|🔴' | head -1)
  [ -n "$flag" ] && ok "llm job $id done, flag $flag" || bad "llm job $id: $(echo "$st" | head -c 300)"
else bad "llm enqueue: $r"; fi

# 6. results on the volume carry the power stamp
n=$($COMPOSE exec -T owl sh -c 'ls /data/results/*/*.json 2>/dev/null | wc -l')
stamp=$($COMPOSE exec -T owl sh -c 'f=$(ls -t /data/results/*/*.json | head -1); python3 -c "import json;print(json.load(open(\"$f\")).get(\"power_hardware\"))"')
[ "${n:-0}" -ge 2 ] && ok "$n result files; latest power_hardware=$stamp" || bad "results on volume: ${n:-0}"

echo "---- $pass passed, $fail failed"
[ $fail -eq 0 ]
