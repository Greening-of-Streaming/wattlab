#!/bin/sh
# Started by the OWL LaunchDaemon through a loopback ssh session (the forced
# command of the id_owl_local key — see install_owl_svc.sh). Copy to
# /Users/gos/owl/owl-serve.sh. Clears any stale OWL still holding :8000, then
# replaces itself with uvicorn so OWL lives exactly as long as the session.
pkill -f "[u]vicorn main:app --host 0.0.0.0 --port 8000" 2>/dev/null && sleep 2
cd /Users/gos/wattlab/wattlab_service || exit 1
exec env PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin HF_HUB_OFFLINE=1 \
  /Users/gos/owl/venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
