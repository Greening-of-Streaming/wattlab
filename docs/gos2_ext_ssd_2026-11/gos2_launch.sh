# runs ON GoS2 after the deploy + restart: preflight, then queue benchmark (variance n=30 inside) + thermal-recovery probe
set -e
cd ~/wattlab
echo "== version =="; git log -1 --format="%h %ci %s"; cat VERSION
echo "== live =="; curl -s -m 5 http://127.0.0.1:8000/live; echo
echo "== flags =="; ls /tmp/owl-lab-session /tmp/owl-paused /tmp/owl-maintenance 2>&1 | head -3
echo "== variance_runs / bench =="; python3 -c "import json;s=json.load(open('settings.json'));print({k:s[k] for k in ('variance_runs','bench_video_reps','bench_sources','bench_run_video','bench_run_llm','bench_run_rag','bench_run_image')})"
echo "== spotlight =="; mdutil -s /Volumes/GoS2-Ext | tail -1
echo "== top cpu =="; ps -Ao %cpu,comm -r | head -4
echo "== launch benchmark =="; curl -s -m 20 -X POST http://127.0.0.1:8000/benchmark/run -H "Content-Type: application/json" -d '{}'; echo
sleep 3
echo "== launch thermal-recovery probe (queued after) =="; curl -s -m 20 -X POST http://127.0.0.1:8000/precalibration/run; echo
sleep 2; curl -s -m 5 http://127.0.0.1:8000/live; echo
