# GoS2 autonomy plan — from "driven by GoS1" to "two autonomous OWL nodes"

**Status:** drafted 2026-10-05 (owner request); **Phases 1–5 built overnight 2026-10-05/06** (owner decisions:
data root `/Users/gos/owl-data`, GoS2 pages Lab-only, HMAC peer auth, SSH driver retired only after the owner
tests). CR-085 follow-on; implements `docs/gos2_design.md` §2 ("two autonomous peers").

| Phase | Commit | State |
|---|---|---|
| 1 boots anywhere | `e07ce6e` | ✅ `paths.py`/`env.py`, `run_*` startup flags, guard tests |
| 2 macOS layer | `f4534b9` (+ `eac7193`) | ✅ `gpu.AppleBackend`, mps, `owl-focus` |
| 3 GoS2 own OWL | — | ⚠ serving from an **SSH-held session** (`bin/gos2-owl-session`): macOS Local Network privacy blocks LAN access from launchd agents *and* the `owl-svc` LaunchDaemon — owner action needed (see §Local Network) |
| 4 peer API | `2129293` | ✅ `/peer/*`, HMAC, simultaneous runs, offline greying; GoS1's registry now `driver: peer` |
| 5 replication | `01c2390` | ✅ pull-based both ways + members from one writer |

### Local Network (macOS 15+ privacy) — the one open blocker
A process started by launchd (user agent, or a LaunchDaemon with `UserName gos`) gets `No route to host` for
every LAN address (plugs, GoS1) while loopback and internet work. Processes in an SSH session are exempt — hence
the interim holder on GoS1 (if GoS1 or the SSH link dies, GoS2's OWL stops; the holder restarts it when SSH
returns). Fix for the morning: in System Settings → Privacy & Security → Local Network, allow the entry for the
venv's Python (or `uvicorn`) after starting `sudo owl-svc install` once from the desktop session so macOS
prompts; then `touch /tmp/gos2-owl-session.stop` on GoS1 and `sudo owl-svc restart` on GoS2.

### Nice level
`nice -n -5` (GoS1 protocol step 5) **never applied** on either node: the service runs as `gos`, and negative
nice needs root — ffmpeg runs at nice 0 everywhere. Not a parity issue (both equal) but the protocol text
overstates it.

## Goal

**GoS2 is fully operational without GoS1** — its own pages, queue, meters, results and quality scoring — and
GoS1 can still run jobs on GoS2 (and vice versa) through a small authenticated **peer job API**, not SSH.
Minimal stickiness: no large file moves at job time, no shared process, no node reaching into the other's
hardware. Losing either node leaves the other working (minus features that physically live on the lost node,
e.g. the decode rig, NVENC, the RTX AI ladder).

## Where we are (survey 2026-10-05)

| Coupling today | Effect if GoS1 is dark | Removed in |
|---|---|---|
| GoS1's service drives GoS2 over SSH (encode, image runner, MLX, Ollama tunnel, image session pipe) | GoS2 unusable | Phase 4 |
| GoS1 polls GoS2's Tapo plugs (`power.use_meters`) and keeps GoS2's idle floor | breaks after any move | Phase 3 |
| GoS2 jobs run inside GoS1's serial queue; GoS1's pre-job idle guard checks GoS1's meters before a GoS2 job | wrong guard, shared queue | Phase 3–4 |
| Results saved only on GoS1 (`persist.save_result`), GoS2 provenance stamped from GoS1's registry | GoS2 has no history | Phase 3 + 5 |
| Source clips canonical on GoS1, copied to GoS2 by sha256 | ✅ cached copies already independent | — |
| VMAF + probing | ✅ on GoS2 since `a36c6de` | — |
| AI models | ✅ on GoS2 (byte-identical copies) | — |

Portability blockers for running OWL itself on macOS (survey): 28 `/home/gos/wattlab` literals in 15 modules
(CR-031 §3 says ~25/14 — stale), 30 `/srv/data` sites (most via settings), `.env` loaded from an absolute path in
5 modules, unconditional startup of host-specific pollers (decode rig, origin :8123, carbon, RAG), Linux-only calls
(`systemctl` focus mode, `sensors -j`, `nvidia-smi`, `lspci`, `/dev/dri`, `nice -n -5`), `"cuda"` hard-coded in
`image_gen.py`, cu128 torch pin, `tapo` arm64 wheel unverified.

## Principles

1. **One codebase, per-host configuration.** No "GoS2 fork". Host differences live in `settings.json` + `.env`
   + a platform layer, never in `if host == …` branches.
2. **GoS1 behaviour unchanged at every step** — each phase lands with the full suite green and GoS1 measuring
   exactly as before (any pure-software refactor needs no energy re-validation; anything touching a measurement
   path gets a GoS1 n=3 spot check).
3. **Measurement parity is tested, not assumed.** When GoS2 starts measuring standalone, it must reproduce the
   SSH-driven numbers (tonight's campaign) within their CIs before the SSH path is retired.
4. **Each phase is independently useful** and can stop there.

## Phases

### Phase 1 — OWL boots anywhere (no behaviour change on GoS1) · ~1 session
- `paths.py`: `OWL_ROOT` (default = repo root derived from `__file__`, env-overridable) + `DATA_ROOT`; sweep the
  28 `/home/gos/wattlab` literals and the hard `/srv/data` ones (lg.py, pixop.py:1374, routes_enhance.py:1458,
  decode_run.py BENCH_DIR, rig ADB path) — CR-031 §3 pre-work item 1, finally done.
- `env.py`: one `.env` loader (process env wins), replacing the 5 absolute `dotenv_values` sites.
- **Startup feature flags** in settings (`run_rig_poller`, `run_origin`, `run_carbon_poller`, `run_rag_check`,
  `run_sensors_poller`), default true → GoS1 unchanged; GoS2 sets them false.
- `settings.load()` warns loudly when settings.json is missing (today it silently boots with GoS1 paths).
- Make `wattlab_service/` a package (CR-031 §3 item 4) if the sweep needs it.
- **Guard test:** no `/home/gos/wattlab` literal outside `paths.py`.

### Phase 2 — macOS / Apple-silicon platform layer · ~1–2 sessions
- `gpu.AppleBackend` (detected via `platform.system()=="Darwin"` + arm64): VideoToolbox encoders + the VBR/CBR norm
  args already validated in the registry, `-hwaccel videotoolbox`, `scale_vt` (or CPU scale — test), device label,
  stamp. `read_gpu_sensors` via the narrow sudo wrapper `owl-powermetrics` (GPU power, temperature) — the
  wrapper already exists on GoS2.
- **Device-agnostic torch:** remove the `"cuda"` literals in `image_gen.py` — pick cuda → mps → cpu (the pattern
  `remote/owl_imagegen.py` already uses). LLM/RAG already go through Ollama.
- **Focus mode per platform:** Linux keeps `systemctl`; macOS pauses Spotlight indexing, Time Machine and
  softwareupdate scheduling via a new narrow wrapper (`owl-focus on|off`, added to the GoS2 sudoers rule).
- `nice`: use `nice -n 0` / no renice on macOS (negative nice needs root) — record it in provenance.
- `requirements-macos.txt` (torch MPS wheel, `tapo` arm64 — verify the wheel exists first; fall back to the
  `python-kasa`-style local client only if not).

### Phase 3 — GoS2 runs its own OWL · ~1 session
- launchd **user agent** for uvicorn (auto-login `gos` exists, required anyway — §13 headless rule); log to
  `~/Library/Logs/owl/`; restart via the narrow sudo/launchctl path.
- GoS2 `.env`: Tapo credentials + **G1/G2 as its own meters** (`TAPO_P110_IP=.165`, `_2=.22`).
  GoS1 stops polling them (no KLAP contention).
- GoS2 `settings.json`: Homebrew ffmpeg/ffprobe, VMAF model path, data root, startup flags off, its own
  `local_host` identity (so persist stamps `host: GoS2` natively), Lab = GoS2's LAN (§6).
- **First-run variance calibration** (CR-031 rule) and the idle floor re-measured under OWL's own sampler.
- **Parity gate:** standalone GoS2 reruns a slice of tonight's campaign (H.264/H.265 pair, qwen3:4b Ollama+MLX,
  SDXL-Turbo session), n=3 → must sit within the SSH-driven results' CIs.
- At the end of Phase 3: **GoS2 is operational without GoS1** (its own pages at `http://192.168.1.29:8000`, Lab).

### Phase 4 — Peer job API (GoS1 ↔ GoS2) · ~2 sessions
- Endpoints (both nodes run them): `POST /peer/jobs {type, params}` → `{job_id, queue_position}` (enqueue on the
  callee's own queue, 429 when full); `GET /peer/jobs/{id}` → status, stage, queue_position, error, **watts (the
  callee's own meter)**, partial_response, images_done, vmaf progress; `GET /peer/results/{type}/{id}` → the full
  envelope; `POST /peer/jobs/{id}/cancel` (queued: real; running: cooperative, as `/queue/cancel-current` today).
- **Auth:** HMAC bearer from `auth._sign/_verify` generalised (public helpers), purpose `peer`, short TTL, signature
  covers method + path + body hash, nonce cache against replay; `OWL_AUTH_SECRET` shared via Bitwarden (refuse
  peer calls if the secret is the ephemeral fallback). Peer routes do **not** use audience tiers (fixes the §6
  tunnel trap by construction). CR-066 item 2 (trusted-proxy) lands first.
- **Caller side:** GoS1's "Other machines" panels become a peer client — enqueue on GoS2, keep a local job stub
  so `runtime.job_status` proxies stage/watts, then **import the result envelope verbatim** (no re-stamping by
  `save_result`; add `persist.import_result`). Host-prefixed ids already prevent collisions.
- **Inputs:** GoS2 keeps its own source library (synced from GoS1 by sha256 when both are up); a job never
  requires GoS1 at run time once the clip is cached. Upload inputs travel in the peer request (size-capped).
- Keep the SSH driver behind a host setting (`driver: ssh|peer`) until Phase 4 is verified, then remove it.

### Phase 5 — Replication + "either node down" · ~1 session
- Results both ways, append-only, no delete (peer pull of new envelopes, or rsync over the SSH link) — design §4.
- `members.json` one writer (design §4), `OWL_AUTH_SECRET` shared so magic links verify on either node.
- `/findings` + reports come from git on both.
- **Drill:** stop GoS1's service → GoS2 serves its pages, measures, stores; restart GoS1 → results converge.
  Then the reverse.

### Out of scope here (tracked elsewhere)
Public front-door swap and nginx failover (design Phase 2), GoS1 sleep/wake (design Phase 3), the move to another
site and the SSH tunnel (design Phase 5), decode rig on GoS2 (stays GoS1-only).

## Decisions needed from the owner

1. **GoS2 data root** — proposal `/Users/gos/owl-data` (results, uploads, test_content, models).
2. **GoS2's own pages** — Lab-only at first (proposal), or Member-visible?
3. **Peer auth** — HMAC shared secret (proposal; works with or without a tunnel) vs SSH-tunnel-only.
4. **Retire the SSH driver** at the end of Phase 4 (proposal) or keep it as a fallback.

## Verification per phase
- Full pytest suite green; GoS1 n=3 spot check whenever a measurement path is touched.
- Phase 3 parity gate (above) and recorded idle floor; Phase 4: a GoS1-initiated GoS2 job produces a byte-identical
  envelope to the one GoS2 stores; Phase 5: the two-way outage drill.
