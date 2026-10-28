#!/usr/bin/env bash
# OWL container entrypoint.
#   serve           (default) prepare /data, optionally pull models/content, run OWL
#   pull-models     pull the LLM ladder tiers that fit this host (+ image models)
#   fetch-content   download the open-licence test videos
#   shell           bash, for debugging
set -euo pipefail

APP=/app
DATA=${OWL_DATA_DIR:-/data}

# Safe defaults (owl.env overrides). Simulated power until a real source is
# configured — every page says so. Lab tier: without OWL_LAB_CIDRS, OWL's LAN
# rule ("any private IP is Lab") would make every Docker-networked visitor an
# admin; default to the Docker bridge ranges = host-local / SSH-tunnel access.
export OWL_POWER_SOURCE=${OWL_POWER_SOURCE:-synthetic}
if [ -z "${OWL_LAB_CIDRS:-}" ]; then
  export OWL_LAB_CIDRS=172.16.0.0/12
  echo "owl: OWL_LAB_CIDRS unset — Lab tier = loopback + Docker bridge (172.16.0.0/12) only" >&2
fi

prepare() {
  mkdir -p "$DATA"/{results,test_content,corpus,.chroma,uploads,hf,vmaf,pixop,rem_out}
  # Same layout as GoS1: bulk data lives on the data volume, symlinked back
  # into the checkout where the code expects it (paths.repo(...)).
  for d in results test_content corpus .chroma; do
    if [ ! -L "$APP/$d" ]; then rm -rf "${APP:?}/$d"; ln -s "$DATA/$d" "$APP/$d"; fi
  done
  if [ ! -f "$DATA/settings.json" ]; then
    cp "$APP/container/settings.container.json" "$DATA/settings.json"
    echo "owl: seeded $DATA/settings.json from container/settings.container.json"
  fi
  [ -L "$APP/settings.json" ] || ln -sf "$DATA/settings.json" "$APP/settings.json"
  # No .env file in the image: everything arrives as environment variables
  # (env.py lets the process environment win for TAPO_/OWL_ keys).
  touch "$APP/.env"
}

wait_ollama() {
  local url=${OLLAMA_HOST:-http://localhost:11434}
  for _ in $(seq 1 60); do
    curl -fsS "$url/api/tags" >/dev/null 2>&1 && return 0
    sleep 2
  done
  echo "owl: WARNING — Ollama not reachable at $url (LLM/RAG pages will be empty)" >&2
  return 1
}

pull_models() {
  wait_ollama || return 0
  cd "$APP/wattlab_service" && python "$APP/container/pull_models.py" "$@"
}

case "${1:-serve}" in
  serve)
    prepare
    if [ -n "${OWL_FETCH_CONTENT:-}" ]; then "$APP/container/fetch_test_content.sh" || true; fi
    if [ -n "${OWL_LLM_TIERS:-}${OWL_IMAGE_MODELS:-}" ]; then pull_models || true; fi
    cd "$APP/wattlab_service"
    exec uvicorn main:app --host 0.0.0.0 --port "${OWL_PORT:-8000}" --workers 1
    ;;
  pull-models)   prepare; shift; pull_models "$@" ;;
  fetch-content) prepare; shift; exec "$APP/container/fetch_test_content.sh" "$@" ;;
  shell)         prepare; exec bash ;;
  *)             exec "$@" ;;
esac
