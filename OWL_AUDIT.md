# OWL / WattLab Codebase Audit

**Date:** 2026-07-05 · **Code audited:** local checkout at `/Users/nebul2/dev/owl`, commit `60f08cc` (2026-06-30)

**Method:** Nine-dimension multi-agent audit against the shared GoS rubric
(`RUBRIC.md`). Each dimension was assessed independently for maturity (1–5) and
findings (severity critical/high/medium/low/positive, effort S/M/L). Every
medium-and-above and every positive finding was then put through an adversarial
verification pass: a separate reviewer re-checked each claim against the code at
`/Users/nebul2/dev/owl` and returned **confirmed**, **adjusted**, or **refuted**
with notes. Where a verifier adjusted a severity or corrected evidence, this
report uses the corrected value. A final completeness critic looked for whole
classes of issue the dimension reviewers missed; those gaps are recorded
separately (§5) and were **not** adversarially verified.

**Why this supersedes the prior draft.** The first OWL audit (dated 2026-07-02)
was written against a stale checkout (`00b67f4`, 2026-05-30) and then patched with
a diff note; its body described a codebase that no longer existed (an
11,872-line `main.py` monolith with embedded JS, since split). This is a clean
re-audit against the current tree, with no carried-over claims. One consequence
worth stating up front: the prior draft's security section asserted "a full
git-history scan found no committed secret values" — that is now false. A
plaintext LAN-switch admin password was committed to `GOS1_INFRA.md` on
2026-06-27 (commit `d1941a3`), five days *before* that draft was written. See
§3.7.

**Relationship to the 2026-05 audit.** OWL was audited once before, in 2026-05
(`AUDIT_BRIEF.md` / `AUDIT_RESPONSE.md`) — explicitly architecture-only, with
deployment, config, data, and security out of scope. This audit checks
*follow-through* rather than re-litigating: where a recommendation was accepted,
the question is whether it landed. The headline is strongly positive and is
recorded as findings, not buried — the capability/auth spine
(`audience.py` / `capabilities.py` / `queue_control.py`), the `main.py` split
into ~17 routers, the shared-JS extraction, and the test-suite growth all
shipped and are independently verified. The dimensions the prior audit never
ruled on (security, config, data durability, deployment reproducibility) are
first-time assessments here.

**Deployment reality.** OWL runs on GoS1 (Ubuntu, systemd + nginx), live at
`wattlab.greeningofstreaming.org`, with real external GoS members authenticating
via magic-link. It is a single-box lab appliance, not a containerized fleet. The
GoS convergence direction is one-way: OWL moves toward REM's container pattern
where it moves at all (`CR-031` tracks this), never the reverse.

---

## 1. Scorecard

| Dimension | Maturity /5 | One-line state |
|---|---|---|
| Architecture & modularity | 4 | The 2026-06 refactor genuinely landed — thin `main.py`, enforced import direction, capability spine at 94/95 routes; residual debt is HTML-in-Python route bulk and a schema-free jobs dict. |
| Containerization & deployment | 3 | Honest, health-gated systemd/nginx appliance with strong version provenance, but the primary service unit is uncommitted, nginx protections drifted behind new routes, and ~25 hardcoded `/home/gos/wattlab` paths block CR-031. |
| Configuration & secrets | 3 | Genuinely clean secret hygiene undercut by fragmented config plumbing: 5+ `.env` resolution mechanisms where the file beats process env, and a git-tracked `settings.json` the service rewrites at runtime. |
| Data layer | 3 | Provenance-stamped flat-file store with a documented envelope contract, but the nightly backup covers `results/` only and the post-incident backup health check is still an unchecked TODO. |
| Reliability & observability | 2 | Thoughtful fail-soft design and restart recovery, but effectively zero logging, no health-semantics endpoint, no alerting, and a self-recovery watchdog whose sudo step is unprovisioned. |
| Testing | 3 | Real, fast, actively-grown 770-test suite with honest docs, but nothing gates deploys, ~5–7% of tests only pass on the prod box, and the energy arithmetic is untested. |
| Documentation & process | 4 | Exceptional depth and a genuinely practised CR lifecycle, but the last ~11 days shipped undocumented, version discipline stalled at a "pre-refactor" tag, and `GOS1_INFRA.md` carries personal identity + a plaintext password. |
| Agent- & human-editability | 4 | Excellent agent brief and guard-test culture; residual traps are ~5.1k lines of un-linted page JS in Python f-strings, a stale doc arc, and a dangling `REM/CLAUDE.md` cross-link. |
| Security | 3 | Sound capability spine and token crypto, undercut by reflected XSS/open-redirect on the auth pages, a spoofable X-Real-IP trust root, and a plaintext-capable session cookie. |

---

## 2. Urgent triage

Four items dominate. On a live, member-facing host these are the immediate
actions, in priority order:

1. **Fix the reflected XSS + open redirect in the magic-link auth flow
   (`critical`).** `routes_auth.py` interpolates `error`, `next`, and
   `email_norm` into HTML with no escaping (`:123`, `:129`, `:156`), builds the
   emailed verify link with unescaped `next` (`:153`), and does
   `RedirectResponse(url=next or "/")` (`:185`). The module never imports
   `html`; sibling routers do escape, so this is a gap, not house style. All
   three GET routes are `PUBLIC_PAGE`, so `GET /auth/sign-in?error=<script>…` is
   unauthenticated reflected XSS on the trusted auth origin, and
   `?next=https://evil.com` is an open redirect (and an attribute-breakout in
   the outbound email). Fix: `html.escape()` every reflected value and
   allow-list `next` (must start with a single `/`, reject `//`/schemes) before
   using it in inputs, hrefs, emailed links, and `RedirectResponse`.

2. **Stop trusting `X-Real-IP` for Lab tier and bind uvicorn to loopback
   (`high`).** `audience.py:59-63` grants **Lab** (the admin tier: settings
   write, benchmark/variance run, prepare-rem) to any loopback/RFC1918 origin,
   read from the raw `x-real-ip` header with no trusted-proxy check, while
   `README.md:99` and `STAGING.md:29` document uvicorn on `0.0.0.0:8000`
   directly reachable on the LAN. Through nginx the header is overwritten, but a
   direct `:8000` client can send `X-Real-IP: 127.0.0.1` and become Lab — and
   every LAN peer already auto-resolves to Lab via `client.host`. Fix: only
   honour `X-Real-IP`/`X-Forwarded-For` when `request.client.host` is the known
   proxy address; bind uvicorn to `127.0.0.1` in production; firewall/document
   `:8000`. (Note: this same header trust also breaks *inside* a docker bridge
   network, where every container-internal request looks RFC1918 — a CR-031
   blocker the CR does not yet list.)

3. **Rotate and remove the committed switch password; de-personalize
   `GOS1_INFRA.md` (`high`).** `GOS1_INFRA.md:117-118` commits the GS305E switch
   admin password (`Wattlab1`) in cleartext (added `d1941a3`, 2026-06-27, still
   at HEAD); the file also carries the owner's full name/personal email/company
   SIREN (`:8`), Nextcloud backup URL + username + "2FA: not configured"
   (`:125-132`), and a personal-life inventory (`:185-192`) — in the public GoS
   org repo. Treat the password as burned (rotate on both switches), move it to
   the password manager, relocate personal/identity material to a private ops
   note, and scrub. The operationally valuable content (disk layout, incident
   log, backup design) stays.

4. **Close the backup gaps (`high`, data).** The nightly rclone cron syncs only
   `results/` (`GOS1_INFRA.md:57,161`); `data/members.json` (the member
   allowlist), the RAG corpus, keep-class uploads, and the `rem_out` share files
   whose tokens are already circulating are all single copies on one disk. And
   the "backup last-success ≤ 26h" health check promised after a documented
   24-night silent backup failure (`GOS1_INFRA.md:166-177`) remains an unchecked
   TODO (`:164`) two months later — the exact failure class the owner already
   wrote down as "the worst kind." Fix: extend the backup manifest to all
   persistent data classes (encrypted — `members.json`/results carry member
   emails), and ship the cheapest last-success heartbeat into the existing
   watchdog or a `/healthz` field.

---

## 3. Findings by dimension

Each confirmed finding is listed with severity/effort tags, evidence paths,
description, recommendation, and (where relevant) a convergence note. Verifier
corrections are folded into the evidence; where a verifier changed a severity it
is noted inline. Positive findings record follow-through that landed. Low-severity
and small items are collapsed under "Minor".

### 3.1 Architecture & modularity — maturity 4/5

*Summary:* The post-refactor architecture is real layering, not cosmetic
file-splitting. `main.py` (543 lines) is pure app assembly; 17 routers own their
feature surface; shared state (`runtime.py`), chrome (`ui.py`), upload lifecycle
(`uploads.py`), and the access spine are cleanly factored; and the documented
"feature modules never import main" rule holds in the tree. The two remaining
structural debts are deliberate, documented trade-offs: the big `routes_*.py`
files are 65–90% embedded HTML/JS f-strings, and the jobs dict is free-form with
~190 mutation sites.

#### Capability spine held through the router split (`positive`, `S`)
- **Evidence:** 95 route decorators across `routes_*.py` + `main.py`, 94 carry
  `Depends(requires(...))`; the one exception is `POST /auth/sign-out`
  (`routes_auth.py:195`, see §3.9). Policy is one table (`capabilities.py:73`
  `_REQUIRED_TIER`, contract docstring `:4-17`); tier resolution is isolated in
  `audience.py` (75 lines); the single enqueue path `queue_control.enqueue` is
  used at all 14 job-start sites. The invariant is **already machine-enforced**:
  `test_every_route_declares_capability_or_is_waived`
  (`wattlab_service/tests/test_capabilities.py:331`) walks `app.routes` and
  fails on any un-gated route unless waived (`_ROUTE_WAIVERS:298` whitelists
  `/auth/sign-out` and the FastAPI docs endpoints).
- **Description:** The 2026-05 audit's core accepted recommendation — routes
  declare capabilities, never tiers — survived the split into 17 routers without
  erosion. Moving a capability between tiers is a one-row edit.
- **Recommendation:** None; the walk-the-routes guard the prior draft asked for
  already exists.
- **Convergence:** This capability-table pattern is the strongest candidate for
  a GoS-wide auth standard if REM ever grows tiered access.

#### `main.py` monolith genuinely dissolved into enforced layers (`positive`, `S`)
- **Evidence:** `main.py` is 543 lines of assembly (router imports `:45-61`,
  include loop `:63-67`, compatibility alias block `:73-95`); shared job/telemetry
  state in `runtime.py:23-39`; page shell `render_page` at `ui.py:514`; shared
  front-end in `static/wl-*.js` (2,193 lines, cache-busted `?v=sha`). No domain
  module (`video/llm/rag/image_gen/pixop/power/persist`) imports `ui`, `runtime`,
  or `main`; measurement modules receive jobs by parameter injection.
- **Description:** The stale draft's "11,872-line monolith" is gone in substance.
  **Corrections from verification:** (a) there is lateral router-to-router
  coupling (`routes_rem.py:34`, `routes_demo.py:22`, `routes_mockups.py:21`
  import helpers from other routers) — so "no module imports any `routes_*`" is
  false, but these are lateral, not upward; (b) `benchmark.py:59/70/76` lazily
  imports `main` (documented byte-stability exception) — the only upward
  dependency, kept alive by the alias block; (c) `ARCHITECTURE.md`'s map has
  drifted (says `main.py` "~430 lines" vs 543; lists 13 of 17 routers).
- **Recommendation:** State the `benchmark.py→main` exception wherever the "never
  import main" rule appears; refresh the `ARCHITECTURE.md` routes row (also
  §3.7). Once Phases 0-4 are settled, repoint `benchmark.py` at the owning
  routers and delete the alias block so `main.py` becomes import-terminal.
- **Convergence:** Isolating container blockers into `main.py`/`runtime.py`
  directly serves the CR-031 move toward REM's container pattern.

#### Big route modules are template monoliths: 65–90% embedded HTML/JS f-strings (`medium`, `L`)
- **Evidence:** Triple-quoted-string line share: `routes_demo.py` 90%,
  `routes_methodology.py` 87%, `routes_llm.py` 75%, `routes_video.py` 73%,
  `routes_rag.py`/`routes_enhance.py` 70%. Single page functions span hundreds
  of markup lines (`rag_page` `routes_rag.py:46-887`; `_DEMO_HTML` a ~1,227-line
  module-level f-string at `routes_demo.py:214`). Doubled-brace escape burden is
  real: 294 `{{` in `routes_rag.py`, 334 in `routes_llm.py`. No `templates/` dir
  exists; per-page glue JS is still inline (4 `<script>` blocks each in
  rag/llm/enhance).
- **Description:** The split produced correct per-feature ownership, but each big
  router is a Python file wearing an HTML document (`routes_rag.py`'s actual
  Python logic is ~590 of 1,968 lines). Editing a form field means diffing inside
  a giant f-string with no HTML linting or auto-escaping. This was an explicit
  refactor non-goal ("no Jinja2/template engine",
  `docs/architecture_review_2026-06.md:117`), so it is deliberate — but it is now
  the dominant edit-surface cost and these files are the plausible next monoliths.
- **Recommendation:** Without adopting a template engine, move each page body to
  a sibling `templates/<feature>.html` loaded at request time and interpolated
  via `str.format`/`string.Template`; do `routes_demo.py` and
  `routes_methodology.py` first (~90% static markup). Overlaps §3.8.
- **Convergence:** Request-time template loading removes the last import-time page
  baking, easing the immutable-image container model CR-031 targets.

#### Jobs dict remains schema-free with ~190 mutation sites and no state invariants (`medium`, `M`)
- **Evidence:** `runtime.py:23` `jobs: dict = {}` with docstring "deliberately
  free-form … Mutated in place everywhere; never reassign." ~189 `jobs[...]`
  occurrences across 19 files (`video.py` 35, `routes_rag.py` 22, `routes_llm.py`
  20, `image_gen.py` 18, `power.py`/`pixop.py` 15, `llm.py` 15, …). Keys are ad
  hoc per feature; status/stage transitions have no central definition. No
  `TypedDict`/`set_status`/state-machine exists anywhere. Mitigations are real:
  single owner module, parameter injection into measurement modules, single
  enqueue path, disk-recovery fallback (`runtime.py:72-88`).
- **Description:** The prior review's risk #3 is *managed* (disciplined access)
  but not *fixed* (no declared shape). A typo'd key, a stage set after
  `status='done'`, or a renderer expecting a field a writer stopped setting is
  caught only by eyeballing the UI — the exact S37/S39 regression class the
  result-envelope work fixed on the persistence side, still open on the live-job
  side.
- **Recommendation:** Add a `JobRecord` `TypedDict` (status/stage/progress_pct/
  error/result/…) plus a `set_status(job_id, status)` helper asserting legal
  transitions; migrate writers incrementally (routers first, measurement
  callbacks last to respect the byte-stability rule).

#### Result-envelope contract retired the per-mode elif coupling in `persist` (`positive`, `S`)
- **Evidence:** `persist.py:545-574` `_SUMMARISERS` registry (job_type × mode →
  summariser), dispatch in `_summarise` (`:582-599`) with a loud
  `unrecognised_mode` fallback (`:594-598`); introduced by Phase-4 commit
  `ad83fa5`, whose pre-image was a per-mode elif chain. `docs/result_envelope.md`
  documents the add-a-mode contract with soft-fail `_wlBadRecord`
  (`wl-result.js:109`, call sites 330/460/762/831).
- **Description:** Adding a new *mode* within an existing type is now a documented
  ~3-touchpoint edit with loud failure on both write and render paths — a direct
  fix of the S37/S39 regression class. Adding a new *type* is still ~5 touchpoints.
- **Recommendation:** Fold CSV row-shaping into the same registry and derive
  `routes_results.py`'s job_type allowlist (hardcoded five times: `:27,39,73,102,116`,
  also duplicated in `routes_findings.py:459`/`routes_benchmark.py:189`) from
  `_SUMMARISERS.keys()`, minding the intentional narrower demo set and the
  `rem`/`benchmark` special cases.

**Minor.** `pixop.py` (2,078 LOC) is cohesive but accreting ≥4 separable concerns
(preset parsing, normalization/remux, docker contract, measured-run orchestration)
— split along existing seams when next touched (`low`, `M`). · `wattlab_service/`
has no `__init__.py`; all imports are bare top-level, so it only resolves with the
dir on `sys.path` (CWD-dependent) — convert to a package before CR-031 (`low`, `M`).
· `routes_mockups.py` is self-flagged TEMPORARY at `main.py:57` — track its removal.
· `routes_budget.py:63-231` embeds ~230 lines of demo fixture data.

### 3.2 Containerization & deployment — maturity 3/5

*Summary:* An honest single-box appliance: a mutable git checkout run by an
(uncommitted) systemd unit behind a committed nginx vhost, deployed via
`bin/stage-on`/`stage-off` with a maintenance flag, queue drain, and a `/live`
health gate. The operational tooling is genuinely good; the gaps are the
uncommitted primary unit, nginx protections drifting behind new routes, and ~25
hardcoded `/home/gos/wattlab` paths that block CR-031.

#### Primary `wattlab.service` systemd unit not committed anywhere (`high`, `S`)
- **Evidence:** `systemd/` contains only `gpu-clock-pin.service` and
  `owl-maintenance-watchdog.{service,timer}`; `git log --all` shows the primary
  unit was never committed. `systemd/README.md:3` claims "source-of-truth lives
  here in the repo" — false for the one unit that runs OWL. `GOS1_INFRA.md:47`
  references an uncommitted drop-in `wattlab.service.d/mount.conf`
  (`RequiresMountsFor=/srv/data`). `bin/stage-on:93`/`stage-off:52` restart it;
  no doc contains its `ExecStart`/uvicorn args, `User`, or restart policy.
- **Description:** The definition of the primary service exists only in `/etc` on
  a host whose disk-failure risk `GOS1_INFRA.md` itself documents; a rebuild from
  the repo would be misled by the README's source-of-truth claim. Every auxiliary
  unit got committed; the primary one did not.
- **Recommendation:** Copy `wattlab.service` and `wattlab.service.d/mount.conf`
  into `systemd/` with the same install/verify block the other units have; commit
  the `/etc/cron.d/wattlab-results-backup` line alongside it.
- **Convergence:** REM's `compose.yml` is its complete committed deployment
  manifest; OWL's systemd equivalent should reach the same bar before CR-031
  reuses it.

#### 25 hardcoded `/home/gos/wattlab` paths across 14 Python modules — main CR-031 blocker (`medium`, `M`)
- **Evidence:** 25 occurrences in `.py` (≈39 including `bin/`/`infra/`/`systemd/`).
  Core: `persist.py:13` (RESULTS_DIR), `settings.py:4` (SETTINGS_FILE) and
  `:170-171` (rag paths), `main.py:39`/`power.py:38`/`carbon.py:37`
  (`dotenv_values('/home/gos/wattlab/.env')`), `sources.py:35-110` (7 content
  paths), `parity.py:79-81`, `routes_enhance.py:47-48`, etc. Contrast:
  `auth.py`, `email_send.py`, `findings.py`, `version.py` already resolve from
  the repo root — the portable pattern exists in-tree.
- **Description:** The service cannot run from any other location — not in a
  container, not on a rebuilt host, not a dev clone. The `.env` triple-load is the
  worst offender (silently yields empty config off-host). Hardcoding is legacy,
  not policy — half the modules already do it right.
- **Recommendation:** One `OWL_ROOT` (default: parent of `wattlab_service/`,
  env-overridable) in a small paths module; mechanical sweep of the 25 sites.
  Worth doing even if containerization never happens.
- **Convergence:** Env-configurable roots are exactly what REM's compose pattern
  expects; this sweep makes the eventual Dockerfile a volume-mount exercise.

#### Runtime-mutated `settings.json` is git-tracked; deploys run from a mutable tree (`medium`, `M`)
- **Evidence:** `settings.py:4` points `SETTINGS_FILE` at the prod repo root
  `settings.json`; `save()` (`:245-258`) rewrites it in place, and variance
  calibration writes `variance_*_pct` there (`video.py:1298`, consumed by
  `confidence.py:117`). It is git-tracked and not gitignored; commits like
  `7ec0e2d` ("Settings catch-up") periodically re-commit live state.
  `bin/stage-on` does `git checkout <branch>` in that same tree under `set -e`.
- **Description:** A `git checkout`/`pull` can clobber or conflict on the live
  calibration outputs the confidence flag depends on; the tree stays perpetually
  dirty (eroding the `-local` provenance signal); a branch swap can silently
  revert thresholds. If `settings.json` is locally dirty and diverges on the
  target branch, `stage-on` aborts *after* raising the maintenance flag but
  *before* the restart — a half-deployed 503 state.
- **Recommendation:** `git rm --cached settings.json`, gitignore it, ship a
  `settings.example.json` (or rely on `DEFAULTS`, which already boots a fresh box);
  export calibration snapshots explicitly if history is wanted.
- **Convergence:** Matches REM's committed-defaults + volume-supplied runtime
  config; a runtime-written tracked file cannot survive an immutable image.

#### CR-031 containerization: no movement, but honestly tracked with real prep landed (`low`, `L`)
- **Evidence:** `CHANGE_REQUESTS.md:293-316` — §3 "nothing built; timeline
  externally driven," captured 2026-05-04, with an accurate blocker list.
  `version.py:40-46` implements the container-friendly `version.json` path tagged
  CR-031. No Dockerfile/compose exists.
- **Description:** Two months untouched — defensible given it is gated on external
  hosting. But the cheap prerequisite slices (path root, settings split, committed
  service unit) need no external trigger and would de-risk the move.
- **Recommendation:** Add those three slices to CR-031 §3 as ungated pre-work; add
  the docker-bridge X-Real-IP blocker (see §2 item 2) to the CR's blocker list.
- **Convergence:** CR-031 is the OWL-side vehicle for one-way convergence; keeping
  its blocker list current is the cheapest way to keep the goal live.

#### Positive follow-through
- **Staging/rollback workflow (CR-011/CR-015) is committed, health-gated, and
  documented end-to-end (`positive`, `S`).** `STAGING.md` + `bin/stage-on`
  (queue drain, 60s budget) + `bin/stage-off` (refuses to lower the flag until
  `/live` responds) + the maintenance-watchdog timer + a JS-free
  `maintenance.html` that survives restarts. About the best achievable story for
  a one-GPU box. *Enhancement:* log the pre-stage HEAD sha in `stage-on` output.
- **Version/build provenance is strong and already container-aware
  (`positive`, `S`).** `version.py` resolves `version.json` → live git
  (sha/date/dirty) → dev fallback, all fail-soft; every result JSON is stamped
  `{version, sha, dirty, built_at}`; `requirements.txt` is fully `==`-pinned with
  the CUDA-wheel caveat documented. *Enhancement:* commit the script that
  generates `version.json` so the CR-031 path is exercised.

**Minor.** nginx rate-limit coverage has drifted behind the route surface
(`low` — downgraded from medium: `queue_control.enqueue` enforces a global
depth cap of 8 and per-tier concurrent-job caps, and 10 of 12 uncovered
submission endpoints are Member/Lab-gated, so the app layer already blocks queue
flooding; the residue is request-level load on the public `/rag/run` endpoints
plus config-drift hygiene). · `setup-nginx.sh` is a stale one-shot bootstrap that
would fail `nginx -t` on a fresh host (installs a conf referencing certbot files
that don't exist yet) and runs an unconditional Nextcloud `snap set` (`low`, `S`).
· Three modules re-read the same `.env` independently. · The
`/etc/cron.d/wattlab-results-backup` line is host-only, not mirrored in the repo.

### 3.3 Configuration & secrets — maturity 3/5

*Summary:* Secret hygiene is genuinely clean — `.env` gitignored from the start
and never committed, targeted history scans across all 314 commits found no
credential-shaped material, member PII kept out via `data/*` ignore rules. The
weakness is the config *mechanism*: no settings/env layer, six import-time
`dotenv_values()` calls split across two path conventions with file-over-process-env
precedence, plus a git-tracked `settings.json` the service mutates.

#### Secret hygiene clean: no credentials in working tree or git history (`positive`, `S`)
- **Evidence:** `.gitignore:1` ignores `.env`; `git log --all -- .env` shows only
  `.env.example` commits (placeholder-only); credential-pattern scans across all
  314 commits and `git log -p` over `auth.py`/`email_send.py`/`carbon.py` history
  returned nothing; root `.gitignore:11-12` keeps real member emails out
  (`data/members.example.json` only). `auth.py:56-64` falls back to an ephemeral
  random signing key with a logged warning; `email_send.py:44-48` goes SMTP
  dry-run when the password is unset — fail-soft, not fail-with-embedded-default.
- **Note:** This scans the *application* code and history. The plaintext switch
  password in `GOS1_INFRA.md` (§3.7) is a documentation-file credential, in a
  different class, and is real.
- **Convergence:** Matches the GoS-wide expectation that secrets live only in
  untracked env files.

#### Fragmented `.env` resolution: file beats process env, two divergent paths (`high`, `M`)
- **Evidence:** Six import-time `dotenv_values()` sites, three behaviours:
  repo-relative + file-wins (`auth.py:52-57`, `email_send.py:30-35`);
  hardcoded `/home/gos/wattlab/.env` with **no** `os.environ` fallback
  (`power.py:38,51-52,73` for `TAPO_*`; `carbon.py:37,174` for
  `ELECTRICITYMAPS_TOKEN`); hardcoded-path-with-fallback (`analytics.py:33-45`,
  which misleadingly names the literal `_REPO_ROOT`); plus an `os.environ`-only
  family (`pixop.py`, `gpu.py`) and `main.py:39` (dead, unused parse). No
  `env.py`/`load_dotenv`/`OWL_ENV_FILE` anywhere.
- **Description:** There is no single answer to "where does config come from and
  what wins." Process env never wins where both are consulted, and for the two
  most critical secrets (Tapo credentials, carbon token) it is not consulted at
  all — so a containerized or `systemd Environment=` deployment cannot inject
  them. The two path conventions coincide only because prod lives at
  `/home/gos/wattlab`.
- **Recommendation:** One `env.py`: resolve the path once (repo root from
  `__file__`, `OWL_ENV_FILE`-overridable), read once, expose a getter with
  `os.environ`-first precedence (or `load_dotenv()`, which does not override
  process env). Migrate all six call sites and the `bin/` scripts.
- **Convergence:** CR-031 requires process-env-wins semantics — the single biggest
  config blocker to adopting REM's compose pattern.

#### `settings.json` is git-tracked AND the live runtime-mutated file (`medium`, `S`)
- **Evidence:** In `git ls-files`, absent from `.gitignore`; `settings.py:4`
  hardcodes it at the prod repo root; `save()` rewrites it from `POST /settings`
  and from variance calibration; `CLAUDE.md:20` admits "settings.json excluded
  from commit (live state)"; recurring manual sync commits (`7ec0e2d`, `4cda4d1`,
  `6a7c266`, `39a10f2`). `load()` already boots a fresh box from `DEFAULTS`.
- **Description:** (a) every operator change/calibration dirties the prod tree;
  (b) a `checkout`/`pull` can silently clobber the `variance_*_pct` values the
  confidence flag depends on; (c) meaningful history needs manual catch-up commits
  — process by discipline, not mechanism.
- **Recommendation:** `git rm --cached settings.json`, gitignore it, track a
  `settings.example.json`; export calibration snapshots via a small script if
  wanted. (Same root cause as the deployment-dimension finding.)
- **Convergence:** REM keeps mutable state outside the repo in mounted volumes;
  the target for a containerized OWL.

#### `.env.example` and CLAUDE.md document only 7 of ~19 env vars the code reads (`medium`, `S`)
- **Evidence:** `.env.example` (27 lines) + `CLAUDE.md:74-78` cover 7 `TAPO_*`/
  `OWL_AUTH_SECRET`/`OWL_SMTP_*` vars. Read by code but undocumented:
  `ELECTRICITYMAPS_TOKEN` (a real secret, `carbon.py:174`), `OWL_MEMBERS_FILE`
  (`auth.py:95`), `OWL_SMTP_HOST/PORT/FROM_NAME/DRY_RUN` (`email_send.py:38-45`),
  and the `OWL_PIXOP_*`/`OWL_VQA_DIR`/`OWL_HSA_GFX_VERSION`/`OWL_GPU_VENDOR`
  knobs. All fail-soft, which is why the gap is invisible in operation.
- **Recommendation:** Add every read var to `.env.example` (commented-out for
  optional ones) and sync `CLAUDE.md`; a 20-minute grep-driven pass.

#### Follow-through: `.env.example` landed and settings got a parameter classification audit (`positive`, `S`)
- **Evidence:** `c0805bf` (2026-06-11) added the tracked, placeholder-only
  `.env.example`; `docs/wattlab_parameters_audit.md` classifies settings keys as
  Arbitrary/Empirical/Calibrated/Constrained/Operational (answering
  `AUDIT_BRIEF.md:44` item 7), and `settings.py:51` carries a
  calibration-output ownership comment.
- **Caveat (verifier):** the doc classifies only ~21 of the current 87 `DEFAULTS`
  keys — 66 post-May additions (`vmaf_*`, `pixop_*`, `rem_*`, `enhance_*`, …) are
  unclassified, so it is several drift-cycles behind, not one. The follow-through
  is real; keep the doc refreshed as `DEFAULTS` grows.

**Minor.** `main.py:39` `dotenv_values(...)` is dead (never used). ·
`email_send.py:40` hardcodes `greeningofstreaming@gmail.com` as the fallback
sender in code. · `settings.load()/save()` silently drop keys absent from
`DEFAULTS`, which already produced one dead documented override
(`meter_display_name`) with a green test masking it — add the key to `DEFAULTS`
and log dropped keys (`low`, `S`). · `bin/probe-p110-fw:20` hardcodes the path
while its sibling derives it from `__file__`.

### 3.4 Data layer — maturity 3/5

*Summary:* The storage engine is deliberately flat JSON under
`results/{type}/{date}_{job_id}.json` — a choice ratified in 2026-05 and kept
honest by unusually strong provenance (every result stamped with code version,
GPU/meter hardware, inline carbon intensity, visitor key). Weakest on durability
and monitoring: the nightly backup covers `results/` only, and the post-incident
last-success check is still unimplemented.

#### Provenance-stamped flat-file store with a documented envelope contract (`positive`, `S`)
- **Evidence:** `persist.py:47-70` stamps `owl_version`, `gpu_hardware` (CR-060),
  `power_hardware`, inline CO₂e intensity, and `visitor_key` at write time;
  `docs/result_envelope.md` catalogues the shape and its 7 consumers;
  `persist.py:594-599` loud `unrecognised_mode` fallback pinned by
  `tests/test_result_envelope.py`; append-only `history.jsonl` at
  `persist.py:74-92`; `AUDIT_RESPONSE.md:84` ("don't introduce a database").
- **Description:** The 2026-05 "keep flat files" position landed and was improved
  beyond the ask: no hardware or formula change can be silently compared across
  eras, and the S37 regression class is structurally guarded.
- **Recommendation:** Keep as-is; when CR-031 §1 is decided, JSON + a thin SQLite
  index preserves this provenance model with least risk.
- **Convergence:** CR-031 §1 correctly defers the engine choice to GoS-wide
  coherence with REM's TimescaleDB stack.

#### Nightly backup covers `results/` only — members.json, corpus, keep-class uploads, REM share outputs are single copies (`high`, `S`)
- **Evidence:** `GOS1_INFRA.md:57,161` — cron syncs only `results/`.
  `data/members.json` (real emails, gitignored, on the 500GB system disk),
  `uploads_dir` (`settings.py:199`, `/srv/data/owl/uploads`; `uploads.py:43`
  promises keep-class files are "never removed"), `rem_out` share files +
  `share_tokens.json` (`rem_prep.py:110,619`), and the ~280MB corpus + `.chroma`
  are all absent from the cron and (for uploads/`rem_out`) from the disk-layout
  inventory too.
- **Description:** One of five-plus persistent data classes has a second copy. A
  single disk failure loses the member allowlist, the corpus behind published RAG
  findings, every "keep" upload (a user-facing durability promise the infra does
  not honour), and REM-prep deliverables whose share tokens are already
  circulating.
- **Recommendation:** Extend the rclone manifest to
  `/srv/data/owl/{results,corpus,uploads,rem_out}` + `data/members.json`
  (encrypted — the `rclone-crypt` TODO at `GOS1_INFRA.md:162` is still open,
  and results/members carry emails); add `uploads/` and `rem_out/` to the disk
  inventory; decide whether `.chroma` is regenerate-on-restore.
- **Convergence:** Enumerate these as named volumes now so the backup manifest and
  the future CR-031 compose file agree.

#### Backup last-success health check still unimplemented ~2 months after the 24-night silent failure (`medium`, `S`)
- **Evidence:** `GOS1_INFRA.md:164` — the "backup last-success ≤ 26h" check is an
  unchecked TODO; `:166-177` documents the 2026-04-10→05-05 incident (24 nightly
  runs failed invisibly, 98 files missing remotely) with the lesson written twice
  (`:177`, and `:89` for a parallel DuckDNS failure). Greps across
  `wattlab_service/`, `bin/`, `systemd/` find no implementation.
- **Description:** The exact failure class already happened once and the repo
  twice records "silent background jobs need a visible failure signal" — yet
  detection is still zero. Recurrence would accrue invisibly, exactly when the
  single-copy exposure above matters most.
- **Recommendation:** Cheapest visible check — a line in the existing watchdog or
  a `/healthz` field comparing newest result mtime / rclone last-success against a
  26h threshold; or have the cron touch a marker the status UI surfaces.
- **Convergence:** REM's health-check conventions are the GoS pattern — a
  last-success heartbeat surfaced in the service's own status endpoint.

#### Findings catalog silently drops broken findings, and the claimed test safety net cannot see them (`medium`, `S`)
- **Evidence:** `findings.py:112-125` `list_all()` swallows `FindingError` and
  continues, with a docstring citing `test_findings_references.py` "in CI" —
  that file does not exist (tests are `tests/test_findings.py`) and there is no CI
  (`TESTING.md`: "not a gate"). `tests/test_findings.py:50-61` iterates
  `list_all()`, so a finding whose `source_result_id` no longer resolves is
  simply absent and the test stays green; only 6 of 8 published slugs are pinned
  by name. Mitigation that landed: direct `/findings/<slug>` now 500s loudly
  (`routes_findings.py:421-429`).
- **Description:** Since findings are OWL's citable scientific output, silent
  unpublication is a data-integrity failure, not a UI bug — and for the two
  unpinned findings, a green run says nothing. `delete_result` has no
  cited-source guard.
- **Recommendation:** Make the test enumerate the filesystem (`glob
  docs/findings/*.md`, `load(p.stem)`, fail on `FindingError`) — ~6 lines
  replacing the pinned lists and covering every future finding; fix the stale
  comment; add a cited-source guard to `delete_result`.

#### No schema version or migration path for result envelopes (`medium`, `M`)
- **Evidence:** No `schema_version`/`envelope_version` field anywhere; `owl_version`
  identifies the producing code, not the shape. Five tolerant-reader sites carry
  legacy shapes forever: two cooldown shapes (`result_envelope.md:109-123`,
  unification "deferred"), small/large aliases (`persist.py:399-405`), mode-absent
  defaults (`:576-577`), pre-CR-026 `visitor_key`-less records invisible to
  non-Lab listings (`:26-30`), null-padded pre-carbon records (`:236-246`).
- **Description:** Every shape change is handled by making all 7 consumers
  tolerant of both forms, forever — workable at this scale but the cost compounds,
  nothing on disk says which contract a file satisfies, and CR-031 §1 analytics
  will have to reverse-engineer era boundaries from SHAs.
- **Recommendation:** Add `envelope_version: 1` to `save_result` now (absent = 0),
  record shape changes as version bumps in the doc. **Correction (verifier):** the
  "no migration script exists" claim is false — `bin/anonymise-visitor-ips.py` is
  a self-described idempotent data migration; use it as the template for a
  `cooldown→cooldowns` backfill, so effort is smaller than first stated.
- **Convergence:** Versioned envelopes are the precondition for merging OWL
  history into any REM-coherent store.

**Minor.** `RESULTS_DIR` is resolved two ways — `persist.py:13` (absolute) vs
`findings.py:26-28` (repo-relative) — agreeing only on GoS1; make it a settings
key both read (`low`, `S`). · `uploads.py` 3-way retention is well-engineered but
absent from `GOS1_INFRA.md` and the backup, and its sweep failures are silent
except-pass (`low`, `S`). · `delete_result` takes `matches[0]` of a glob without
disambiguating. · CSV exports embed emoji in the disclaimer line.

### 3.5 Reliability & observability — maturity 2/5

*Summary:* The failure-mode *design* is unusually honest — dual-meter degradation
is recorded not hidden, stale locks self-clear at startup, done jobs recover from
disk, and the ops docs carry a written "silent failures are the worst kind"
lesson. But the *observability implementation* is nearly absent: almost no
logging, no health-semantics endpoint, no alerting, and a recovery watchdog whose
sudo step is unprovisioned. The system cannot tell anyone when it is broken.

#### Measurement core has zero logging and dozens of silent exception handlers (`high`, `M`)
- **Evidence:** Only `auth.py` and `email_send.py` import `logging` in all of
  `wattlab_service/`. Across the seven core modules (`llm`/`video`/`power`/`gpu`/
  `image_gen`/`pixop`/`rag`): **76 except handlers, 68 with no raise/print/log of
  any kind, 39 of those a bare `pass`/`continue`/`return`** (the prior "~24" lead
  and the draft's "56" both undercounted/miscounted; corrected here). The only
  diagnostics are 3 `print()` WARNs. `runtime.py:50` `pass # keep stale value`.
- **Description:** Many handlers are deliberate fail-soft with comments — fine as
  behaviour — but with no log line at even DEBUG, every degraded path (sensor
  parse failure, ffprobe timeout, KLAP rebuild, VQA probe failure) is
  indistinguishable from normal operation in `journalctl`. The S24 GPU-sensor
  incident (`JOURNAL.md:1019`, sensors silently returning `None`) is exactly this
  class and already happened.
- **Recommendation:** Add a module logger to each core module and one
  `logger.warning/debug` inside every intentional fail-soft handler (keep the
  semantics). Under systemd this lands in `journalctl` for free; a one-day
  mechanical pass covers all 68 sites.
- **Convergence:** Adopt one GoS-wide logging convention now — it is also the
  prerequisite for CR-031, where stdout logging is the only channel.

#### Job failures recorded as `str(ex)` only — no traceback, no journal entry, lost on restart (`high`, `S`)
- **Evidence:** `queue_control.py:273-275` worker catch stores
  `{stage:'error', error:str(ex)}`; same at 9 route sites. `import traceback`
  appears nowhere in `wattlab_service/`. `jobs` is in-memory (`runtime.py:23`);
  `_recover_from_disk` recovers only *done* results, so error jobs vanish on
  restart, as does the memory-only `pending_queue`.
- **Description:** A failed run's entire record is one message in a transient dict.
  "NoneType is not subscriptable" with no traceback/timestamp is near-undebuggable
  after the fact, and a restart erases even that; queued users never hear back.
- **Recommendation:** In the worker catch, `logging.exception` (traceback to
  journald) and append `{job_id, type, ts, error, traceback}` to
  `results/diagnostics/job_failures.jsonl` (the CR-012 `history.jsonl` pattern
  already exists); optionally have `_recover_from_disk` answer "error" from it.

#### No health-semantics endpoint, no uptime monitoring — service death is invisible without ssh (`high`, `S`)
- **Evidence:** No `/health`/`/healthz` anywhere. `/live` (`main.py:307`) exists
  and — **correction (verifier)** — is mapped to `Tier.Anonymous`
  (`capabilities.py:78`), so it is effectively public and *could* be monitored
  today; but it returns 200 with all-`None` values (no `watts_age_s`, no
  `last_result_ts`), so degraded-but-alive is invisible. `nginx` has no
  `error_page 502`, so a crashed FastAPI serves raw 502 to members. No
  monitoring/alerting tooling exists; the backup heartbeat is still an unchecked
  TODO 8 weeks on.
- **Description:** A live member-facing service with nothing watching it — the
  first signal of a wedge, dead Tapo path, or power loss is a member complaint.
  The owner already wrote the lesson this violates.
- **Recommendation:** Add self-health fields to `/live` (or an ungated `/healthz`)
  — `{ok, watts_age_s, queue_depth, last_result_ts}`; point a free external
  monitor at it; wire the backup cron to a dead-man's-switch ping. All three are
  an afternoon, and monitoring the existing public `/live` needs zero code.
- **Convergence:** One GoS-wide uptime monitor (e.g. Uptime Kuma on REM's Linode)
  should watch both public endpoints — one standard, two targets.

#### Tapo failure freezes live power readings with no staleness signal (`medium`, `S`)
- **Evidence:** `runtime.py:44-51` power_poller does `pass # keep stale value` on
  any exception with no last-success timestamp; `/power` and `/live` serve
  `power_cache['watts']` with no age field, so `watts` never becomes `None` after
  the first success. Nuance: actual measurement runs *do* fail loudly
  (`power.py:63-84` raises after 3 retries), so this corrupts the live view and
  masks a dead meter between runs, not the results.
- **Recommendation:** Store `ts` alongside `watts`; emit `watts_age_s` and
  null/stale-flag beyond ~30s; feed the same age into `/healthz`.

#### Maintenance watchdog's recovery step depends on non-interactive sudo that nothing provisions (`medium`, `S`)
- **Evidence:** `owl-maintenance-watchdog.service` runs as `User=gos` with no TTY;
  it execs `stage-off`, which runs `sudo systemctl restart wattlab`
  (`stage-off:52`) under `set -euo pipefail`. `bin/README.md:83` confirms the sudo
  is interactive; the only sudoers file is `wattlab-focus` (focus timers), no
  NOPASSWD grant for the restart exists. `CLAUDE.md:133`/`JOURNAL.md:697,978`
  confirm restarts always route to the owner manually.
- **Description:** When the flag goes stale, sudo fails without a prompt,
  `stage-off` aborts before removing `/tmp/owl-maintenance`, and visitors keep
  seeing the maintenance page — the precise failure CR-015 was built to prevent,
  leaving only an unwatched journal line. Has likely never fired in anger.
- **Recommendation:** Either version an `infra/sudoers.d/wattlab-restart`
  (NOPASSWD for exactly `/usr/bin/systemctl restart wattlab`), or give
  `stage-off` a `--no-restart` path for the watchdog (lowering the flag needs no
  restart when no branch switch occurred). Test by firing the timer with a stale
  flag.

#### Positive follow-through
- **Restart and reboot recovery mechanisms landed and documented (`positive`, `S`).**
  `_recover_from_disk` re-serves done results after a restart (fixes the
  2026-06-12 "not_found forever" bug); startup unlinks a stale measurement lock
  (2026-06-10 stop-timeout kills); `RequiresMountsFor=/srv/data`; reserved IPs
  remove DHCP drift. Each cites the incident that motivated it.
- **Dual-meter and measurement error paths fail honestly, never silently upgrade
  (`positive`, `S`).** Secondary-meter failure marks the stream `degraded` and
  continues primary-only; primary reads retry 3× with KLAP rebuild then raise
  into the job error path. The correct posture for a metrology tool — add only a
  log line on the degraded transition (covered above).

**Minor.** Diagnostics use bare `print()` (reach journald only via stdout). ·
`focus_mode_enter` silently drops units whose `sudo systemctl stop` failed, and
the stopped-units list is never stamped into the result — a noisier-than-claimed
environment goes unrecorded. · Fire-and-forget background tasks with no
done-callback; an exception outside the worker's `coro_fn` wrapper would kill the
queue silently. · Analytics middleware swallows all exceptions (`main.py:130-137`).

### 3.6 Testing — maturity 3/5

*Summary:* The suite is genuinely real — 41 files / 644 functions expanding to
770 collected tests in <20s, with clear tiers (TestClient route tests, pure-logic
units, source-level factorisation guards), heavy fixture discipline, and tests
landing alongside features (84 of the last 300 commits touch `tests/`).
`TESTING.md` was rewritten to reality and the access-spine tests landed in full.
The gaps: no CI/gate, ~5–7% of tests only pass on GoS1, and the modules that
produce the product's actual numbers are the least-tested.

#### Substantial fast suite grown in lockstep with features (`positive`, `S`)
- **Evidence:** 41 test files, 644 `def test_`, 770 collected in <1s, ~18s full
  run (714 pass off-box); 84/300 recent commits touch `tests/`; ~925
  monkeypatch/tmp_path uses; guard families (`test_js_bundling.py`,
  `test_gpu_ui_factorisation.py`, `test_page_model_defaults.py`); per-session
  counts tracked in `CLAUDE.md`.
- **Description:** Not audit theatre — large, fast, layered, growing with every
  session. The strongest single asset a future refactor (including CR-031) can
  lean on. Keep the runtime under 20s.

#### Prior-audit testing commitments landed cleanly (`positive`, `S`)
- **Evidence:** `AUDIT_RESPONSE.md:45-47,71` accepted "tests land with the access
  spine (~30 lines)"; delivered `test_auth.py` (21), `test_audience.py` (18),
  `test_capabilities.py` (31) — an order of magnitude beyond the ask, all passing
  in a clean env. `TESTING.md:3` records the 2026-06-11 rewrite deleting the
  never-written `smoke.sh`/`integration.sh` fiction.

#### Nothing gates deploys — tests are policy-exempt by design (`high`, `S`)
- **Evidence:** No `.github/`, no git hooks, `pytest` absent from any
  requirements, `stage-on`/`stage-off` invoke no tests, `TESTING.md:21` "run as a
  habit, not as a gate" and `:150` "not a CI gate." (`stage-off` does wait on
  `/live`, but that is process-liveness only, and nothing forces deploys through
  the stage scripts.)
- **Description:** A production service with real members deploys via `git pull` +
  restart with zero automated verification between keystroke and live traffic. One
  forgotten run ships a broken build to `wattlab.greeningofstreaming.org`.
- **Recommendation:** Cheapest first step — a pre-push hook running
  `pytest tests/` (~18s) plus a pytest run inside `stage-on` before restart.
  GitHub Actions can wait until the suite is portable (next finding).
- **Convergence:** Wiring a gate now makes the CR-031 move to a REM-style
  build/deploy flow a lift-and-shift rather than a redesign.

#### Suite only fully passes on GoS1 — tests are bench-box-coupled with no skip markers (`medium`, `M`)
- **Evidence:** Off-box runs yield 40–56 failures of 770 (count floats with which
  host tools are present). Causes: hardcoded `/srv` paths (`settings.py:112-199` →
  `OSError` in `test_uploads`/`test_rem_prep`), `gpu.py:189` "No discrete GPU
  detected" (7/9 of `test_encode_norm`), `test_findings` needs live production
  results, `test_sources` needs real media files. `skipif` exists only for
  missing `node` (`test_ui_config.py`), never for GPU/`/srv`/results couplings.
  Collection from the repo root also aborts (`main.py:71` cwd-relative
  `StaticFiles` mount), contradicting `conftest.py`'s "run from anywhere."
- **Description:** ~5–7% of the suite silently assumes the prod box's filesystem,
  GPU, and accumulated data — the direct blocker to a CI gate, to CR-031, and to
  any contributor running it, and the failures are confusing errors rather than
  clean skips.
- **Recommendation:** Add `@pytest.mark.gpu`/`gos1_data` with skipif conditions;
  route test writes through `tmp_path`/settings overrides; give `test_findings` a
  fixture `results/` tree. Then `pytest tests/` is green anywhere.
- **Convergence:** A container-runnable suite is a precondition for REM's
  docker-compose pattern under CR-031.

#### Core measurement modules and energy arithmetic have no direct tests (`medium`, `M`)
- **Evidence:** No `test_llm.py`/`test_rag.py`/`test_image_gen.py`. The energy
  formula `delta_e_wh = round(delta_w * (delta_t/3600), 4)` is duplicated inline
  **eight** times (`llm.py:267,503`, `rag.py:590`, `image_gen.py:264`,
  `video.py:677`, `pixop.py:1646`, `parity.py:373`, `rem_prep.py:420`) plus two JS
  re-implementations — none unit-tested (the only assertion on `delta_e_wh` is
  `is not None`). `/llm`, `/rag`, `/image` have no route-level tests beyond page
  fetches.
- **Description:** The product's entire output is energy numbers, yet the code
  computing them is the least-tested in the repo. A sign-flip or unit error in one
  of the eight copies would pass green. The pure arithmetic and mode-orchestration
  need no hardware.
- **Recommendation:** Extract one `energy_wh(delta_w, delta_t_s)` helper (eight
  call sites) with unit tests (rounding/zero/negative edges); add tests for
  `llm`/`rag`/`image_gen` summarisation maths with mocked power, mirroring
  `test_pixop.py`.

#### Non-Lab route behaviour under-tested: TestClient defaults to full-access Lab tier (`medium`, `S`)
- **Evidence:** `TESTING.md:39` documents it ("loopback resolves to Lab … this bit
  us in S37: a `/findings` 404 for every non-Lab visitor was invisible to a green
  suite"). Only ~5 files actually exercise non-Lab tiers over HTTP; the CR-026
  anonymous-leak checks (403 upload, 404 cross-visitor download, `/`→`/demo`
  redirect) live only in the manual Tier-3 checklist, not automated.
- **Description:** The known-worst regression class — a green suite hiding a break
  for every external visitor — is documented but half-mitigated: tier scoping is
  unit-tested at the persistence/capability layers while the route layer that
  serves anonymous/member traffic is exercised almost exclusively as Lab.
- **Recommendation:** A parametrized anonymous-tier smoke test (~30 tests) for each
  public page and CR-026 invariant, using a public `x-real-ip` and no cookie.

**Minor.** No coverage tooling anywhere. · Test environment unpinned — `pytest`,
`pytest-asyncio`, `PyYAML` are implicit in GoS1's venv; add a `requirements-dev.txt`
and a `pytest.ini` registering the asyncio marker (`low`, `S`). · Documented test
counts drift across README (628) / TESTING (662) / CLAUDE (704) vs 770 actual.

### 3.7 Documentation & process — maturity 4/5

*Summary:* One of the best-documented single-maintainer projects a reviewer will
see — a lean auto-loaded `CLAUDE.md`, a 98-line `ARCHITECTURE.md` at the right
altitude, a genuinely practised CR lifecycle (14 active, 50 closed), superseded
docs banner-marked. The flaws are specific: the "keep current" contract broke on
2026-06-19, `GOS1_INFRA.md` mixes personal identity with a plaintext password, and
version discipline stalled.

#### 2026-05 audit recommendations fully landed (`positive`, `S`)
- **Evidence:** Every accepted item shipped — `audience.py`/`capabilities.py`/
  `queue_control.py` with tests; a 98-line `ARCHITECTURE.md` matching the layering;
  JS in real static files; `TESTING.md` rewritten. The "CAPABILITIES.md mirror"
  idea was consciously *dropped* in favour of policy-in-code
  (`capabilities.py:4` "This file IS the security policy").
- **Convergence:** "Policy lives in code, docs mirror it" is worth adopting as the
  GoS-wide standard for REM too.

#### Personal identity, backup endpoints, and a plaintext admin password in `GOS1_INFRA.md` (`high`, `S`)
- **Evidence:** `:8` owner full name / personal email / company SIREN; `:117-118`
  GS305E switch admin password `Wattlab1` in cleartext (committed `d1941a3`,
  2026-06-27, present at HEAD); `:125-132` Nextcloud URL + username + "2FA: not
  configured"; `:185-192` a personal-life inventory. `README.md:9` confirms this
  is the public org repo.
- **Description:** The prior audit's concern about personal detail in an org repo
  has grown, not shrunk: a LAN device admin password is now committed in
  cleartext, and the file doubles as reconnaissance for anyone with repo access.
  **Correction (verifier):** the password predates the 2026-07-02 draft by five
  days, and that draft's "no committed secret values" claim is therefore wrong —
  the credential is in git history (`d1941a3`) regardless of any future doc edit.
- **Recommendation:** Rotate the switch password and remove it (reference the
  password manager); move identity + "Broader Stack" to a private note; scrub the
  Nextcloud username/endpoint; treat the old password as burned. Keep the disk
  layout / incident log / backup design.
- **Convergence:** One GoS standard — infra credentials and personal identity live
  in a private ops store, never in the org git tree.

#### Documentation contract broke on 2026-06-19: the prepare-REM arc is undocumented everywhere (`medium`, `M`)
- **Evidence:** `CLAUDE.md:3` and `JOURNAL.md:10` both stop at Session 53
  (2026-06-19), but `git log` shows **16** commits through 2026-06-30 — a whole
  new user-facing `/prepare-rem` page (`routes_rem.py`, 652 lines), a unified
  `uploads.py`, a new finding, a GPU SM-clock pin. `prepare-rem`/`rem_prep`
  appears nowhere in `CLAUDE.md`/`ARCHITECTURE.md`/`JOURNAL.md`/`CHANGE_REQUESTS.md`.
  `CR-008` still says step-3 interop "remains — longer horizon" although
  `rem_prep.py` (that work) shipped. `ARCHITECTURE.md` counts have drifted
  (`main.py` "~430" vs 543; 13 routers listed vs 17).
- **Description:** Through S53 the journal/header cadence was near-perfect; then an
  entire feature arc exists only as commit messages. `CLAUDE.md` is the
  auto-loaded context file and `ARCHITECTURE.md` is "READ FIRST" — their staleness
  degrades every future AI-assisted session.
- **Recommendation:** Write the S54 JOURNAL entry (06-20→06-30), refresh the header,
  add `rem_prep.py`/`uploads.py`/`analytics.py` and the four missing routers to the
  `ARCHITECTURE.md` map (fix the line count), update CR-008's status, sync the
  findings slug list.
- **Convergence:** This undocumented arc *is* the REM↔OWL integration surface
  (CR-008) — the gap lands hardest on the convergence effort.

#### Version/release discipline stalled at the "pre-refactor rollback anchor" (`medium`, `S`)
- **Evidence:** `VERSION` = `0.8.7`, last bumped 2026-06-10 ("pre-refactor
  checkpoint"); `ARCHITECTURE.md:98` calls `v0.8.7` the rollback anchor while HEAD
  is **111 commits past it** (full refactor, GDPR analytics, parity harness,
  prepare-REM). Tags regress numerically: `v1.0.0`/`v1.1.0` (04-05), `v1.2.0`
  (04-24), then `v0.8.7` (06-10) — two coexisting schemes. `README.md:9`
  advertises "Current release: v0.8.7" publicly.
- **Description:** The version number communicates nothing: "current release"
  equals the rollback checkpoint, and the tag history reads as if the project went
  backwards. Mitigated at runtime by the build stamp, but doc/release-facing
  versioning is incoherent.
- **Recommendation:** Pick one scheme (the 0.x series appears real), annotate the
  April v1.x tags as historical, bump `VERSION` to cover the refactor + June work,
  add "bump VERSION" to the session-close checklist.
- **Convergence:** REM ships version-stamped releases; OWL should converge on the
  same tag-per-release habit.

#### CR lifecycle is genuinely practised, with a high-quality closed archive (`positive`, `S`)
- **Evidence:** `CHANGE_REQUESTS.md:5` states the lifecycle and it is followed: 50
  closed CRs (1,970 lines), all 14 active carry dated Status lines with
  shipped/remaining sub-state (CR-031 tracks three sub-sections), standing design
  principles are first-class entries (incl. the CR-039 open tension awaiting owner
  ratification).
- **Caveat (verifier):** only 22/50 closed entries actually name a closing commit
  hash as line 5 promises; four say "TBD"/"pending." Back-fill discipline exists
  (CR-052/053/061 were reconstructed), so this is an unfinished grooming item, not
  a process failure — back-fill the missing hashes at the next pass.

#### README is fresh-clone accurate on the mechanics that matter (`positive`, `S`)
- **Evidence:** `pip install` + `cp .env.example .env` + the run-from-
  `wattlab_service/` uvicorn invocation all work; `.env.example` covers every var
  the service needs with the *current* auth/SMTP names (verified against code, not
  just docs); the hardware table correctly reflects the RTX 5080 swap. Remaining
  staleness (test count, a 2-of-4 image-gen model row) is cosmetic.

**Minor.** `CLAUDE.md:25` "14 active CRs" vs `:144` "15." · `routes_mockups.py`
TEMP module still mounted 3 weeks on with no removal CR. · `JOURNAL.md` is a single
2,616-line file with no archive split (unlike the CR docs) — worth a policy before
it doubles. · Root strays dilute the tree: `rag_experiment.py` (superseded),
`data_analysis_nov25/`, `data_cleanup/`, generated `DEMO_GUIDE.html`, `rem-theme.css`
(a REM artifact) — move to `docs/archive/` or the REM repo (`low`, `S`).

### 3.8 Agent- & human-editability — maturity 4/5

*Summary:* OWL is unusually editable for a single-maintainer appliance:
`CLAUDE.md` is a real agent brief with bold anti-drift rules, `ARCHITECTURE.md`
writes down the add-a-mode convention, and — rarest of all — the conventions are
enforced by dedicated guard tests. Residual traps: ~5.1k lines of un-linted page
JS in Python f-strings, the stale doc arc (§3.7), a dangling cross-link, and
machine-absolute config paths.

#### CLAUDE.md + ARCHITECTURE.md are a genuine agent brief with written conventions (`positive`, `S`)
- **Evidence:** `CLAUDE.md` states imperatives an agent can obey mechanically —
  "MODELS dicts are live views, never edit as literals" (`:86`), "feature modules
  NEVER import main" (`:102`, verified zero `import main` in any router), single
  cooldown dispatcher (`:118`), "policy lives ONLY in capabilities.py" + the
  TEST-NET/Lab-tier gotcha (`:138`). `ARCHITECTURE.md` has the add-a-mode
  checklist (`:72`), "conventions to hold" (`:95`), and an honest "known weaknesses
  (accepted)" list (`:76`) that stops agents re-fixing accepted debt.
- **Recommendation:** Add a one-liner convention for "adding a routes_*.py module"
  (register in main + ARCHITECTURE table + count) since that list has drifted.

#### Guard-test family enforces editability conventions (accepted 2026-05 item landed) (`positive`, `S`)
- **Evidence:** JS in real static files (2,193 lines across 6 bundles);
  `test_ui_config.py:111-118` runs `node --check` on every static bundle
  ("the check the in-Python-string era never had"); `test_js_bundling.py`
  pins bundle/definition coupling and load order; `test_gpu_ui_factorisation.py`
  flips `gpu.BACKEND` AMD↔NVIDIA and asserts page copy tracks it. `node --check`
  passes on all six bundles.
- **Description:** The accepted recommendation was executed and fossilised into
  regression guards — exactly the anti-drift machinery the rubric asks for.

#### ~5,100 lines of page JS still live inside Python f-strings, unchecked by any linter (`medium`, `L`)
- **Evidence:** Inline `<script>` content in `routes_*.py` totals ~5,100 lines
  (rag 945, llm 893, enhance 869, demo 715, video 675, …) vs 2,193 extracted —
  **70% of the JS corpus is still inline**, forcing brace-doubling (370 `{{` in
  `routes_llm.py`). `test_ui_config.py` runs `node --check` only on `static/*.js`;
  `test_js_bundling.py` only string-matches rendered pages; no JS linter config
  exists, so nothing parses the inline blocks.
- **Description:** The extraction deliberately stopped at shared bundles. Every
  edit inside those blocks needs mental brace-escaping (a stray `{` breaks render;
  a JS syntax slip ships silently — the S38 bug class the bundle check was built
  for, still uncovered for per-page JS). A 1,968-line `routes_rag.py` that is ~half
  JS-in-f-string is the single riskiest edit surface in the repo.
- **Recommendation:** (S) a pytest that renders each page via TestClient, extracts
  inline `<script>` bodies, and runs `node --check` — closes the syntax gap
  without moving code; (L) continue per-page extraction (`wl-llm.js`, `wl-rag.js`)
  as pages are next touched. Overlaps §3.1.
- **Convergence:** Per-page extraction moves OWL toward REM's served-static-asset
  pattern and eases CR-031.

#### Orientation docs frozen at 2026-06-19 while a whole feature shipped undocumented (`medium`, `S`)
- Same root event as §3.7's documentation-contract finding, from the editability
  angle: an agent orienting today would not learn `/prepare-rem`, `routes_rem.py`,
  or `rem_prep.py` exist, and would trust three mutually inconsistent
  module/CR/test counts. Fix: the S54 journal/header update + `ARCHITECTURE.md`
  map refresh, and replace hard counts with a single canonical location.

#### settings.py: deploy-absolute paths and silent-fallback load (`medium`, `M`)
- **Evidence:** `SETTINGS_FILE` and the `.env`/rag/`/srv` paths are hardcoded to
  one machine; `load()` (`:235-242`) has a bare `except Exception: pass` →
  returns `DEFAULTS` with no log line. Because `save()` merges against `load()`,
  the first POST after a corrupt read *permanently rewrites* the file with
  `DEFAULTS` — silently discarding live `variance_*_pct` calibration. `POST
  /settings` passes a raw dict to `save()` with no type validation.
- **Description:** The flat, richly-commented `DEFAULTS` is a strength for
  editability, but the module is wired to one filesystem and fails silently off it.
- **Recommendation:** Derive the paths from an env var (current values as
  defaults); log a warning instead of passing in `load()`; add a minimal per-key
  type check in `save()` against `type(DEFAULTS[k])`.
- **Convergence:** Env-derived paths are the concrete prerequisite for CR-031.

#### GPU-vendor factorisation held — one stale user-visible literal escaped the guard (`low`, `S`)
- **Evidence:** The `gpu.py` backend registry + `ui.py` vendor-resolved copy
  helpers mean the RTX 5080 swap needed zero code edits, and
  `test_gpu_ui_factorisation.py` guards `/video`/`/settings`/`/methodology`. But
  `/rag/compare` is not in the guard's page list, so `routes_rag.py:1619` still
  renders "Ryzen 9 7900 + RX 7800 XT" to users — wrong hardware on a public
  methodology block for 5 weeks.
- **Recommendation:** Replace the literal with `ui._gpu_display_name()`; add
  `/rag/compare` and `/llm/compare` to the guard, or add a repo-wide test
  asserting no `routes_*.py` contains "RX 7800" outside comments.

#### OWL / WattLab dual identity is declared and consistently partitioned (`positive`, `S`)
- **Evidence:** `CLAUDE.md:21` declares the rule (public = OWL, legacy/internal/
  repo = WattLab); user-facing copy, auth pages, and emails consistently say OWL
  (zero user-facing "WattLab" strings outside module paths); infrastructure keeps
  WattLab. The only wrinkle (the public URL carrying the legacy name) is itself
  documented. Not an agent trap.

#### CLAUDE.md cross-link to `REM/CLAUDE.md` is dangling (`low`, `S`)
- **Evidence:** `CLAUDE.md:32` points at "REM/CLAUDE.md — sibling project," but no
  `CLAUDE.md` exists in the REM checkout at all.
- **Description:** The one cross-project pointer in the brief cannot be followed —
  an agent asked to reason about REM↔OWL convergence (an explicit goal) hits a
  dead link at the first hop.
- **Recommendation:** Create REM's `CLAUDE.md` (it is REM's gap, not OWL's) and
  make the pointer a resolvable path, or repoint at REM's README/repo URL.
- **Convergence:** A GoS standard — every project has a `CLAUDE.md` and cross-links
  use resolvable paths — makes multi-repo agent work reliable both directions.

**Minor.** `main.py:49` import comment still calls `routes_budget` "DEMO
illustrative data" though S53 wired it to auto-flip to measured data. ·
`CLAUDE.md:3-20` carries an 18-line session blob in the header, violating its own
"keep it lean" rule. · `TESTING.md:31`'s import-path gotcha (bare `pytest` from
repo root collects nothing) is real but not surfaced in `CLAUDE.md` where an agent
looks first.

### 3.9 Security — maturity 3/5

*Summary:* A genuine, coherent auth spine — one tier resolver (`audience.py`), a
capability table that *is* the policy (`capabilities.py`), and 94/95 routes gated
after the split — with cryptographically sound token/cookie handling (HMAC-SHA256
+ `compare_digest`, purpose separation, expiry, uuid4 share tokens, basename
traversal guards, no `eval`/`exec`/`pickle`/`yaml.load`/`shell=True`). Against
that strong base sit real, exploitable gaps concentrated on the member-facing
edge.

#### Reflected XSS + open redirect across the magic-link auth flow (`critical`, `M`)
- **Evidence:** `routes_auth.py:123` injects `error` raw into `<p class="err">`;
  `:129` injects `next` raw into `value="{next}"` (attribute breakout); `:156`
  reflects `email_norm` raw; `:153` builds the emailed link with unescaped `next`;
  `:185` `RedirectResponse(url=next or "/")`. The module never imports `html`;
  sibling routers do escape, so this is a gap, not convention. All three GET
  routes are `PUBLIC_PAGE` — reachable unauthenticated.
- **Description:** The highest-trust surface. `GET /auth/sign-in?error=<script>…`
  and `?next="><script>…` are reflected XSS on the app origin; `next` is neither
  escaped nor allow-listed, so `/auth/verify?…&next=https://evil.com`
  302-redirects a just-authenticated member off-site, and the unescaped `next` is
  also embedded in the emailed href. `httponly` blunts cookie theft, but XSS still
  drives authenticated actions.
- **Recommendation:** `html.escape()` every reflected value; allow-list `next`
  (single leading `/`, reject `//`/schemes/control chars) before using it in
  inputs, hrefs, emailed links, and `RedirectResponse`; URL-encode `next` in the
  magic-link query.
- **Convergence:** REM's Traefik/container edge would not fix app-level output
  encoding — OWL owns this regardless of CR-031.

#### Lab/admin tier granted from spoofable X-Real-IP with no trusted-proxy gate; uvicorn documented on 0.0.0.0:8000 (`high`, `M`)
- **Evidence:** `audience.py:59-63` grants Lab from `x-real-ip` (falling back to
  `client.host`) if loopback/private, with no check that the connection came from
  the nginx socket. `README.md:99` (`--host 0.0.0.0`) and `STAGING.md:29`
  (`http://192.168.1.62:8000 — direct to FastAPI`) show uvicorn reachable
  off-proxy. `queue_control.py:64` uses the same unguarded pattern.
- **Description:** Lab is the admin tier (settings write, benchmark/variance,
  prepare-rem). nginx overwrites `X-Real-IP` so spoofing is blocked *through* the
  proxy, but a direct `:8000` client can send `X-Real-IP: 127.0.0.1` and become
  Lab, and every LAN peer already auto-resolves to Lab via `client.host`. No
  defence-in-depth beyond the perimeter firewall.
- **Recommendation:** Only honour `X-Real-IP`/`X-Forwarded-For` when
  `request.client.host` is the known proxy; bind uvicorn to `127.0.0.1` in prod;
  document that direct `:8000` must be firewalled.
- **Convergence:** Under REM's Traefik termination the trusted-proxy identity is
  explicit; OWL's nginx+uvicorn hop should adopt the same proxy-gated header trust
  (CR-031). (This trust also silently breaks inside a docker bridge — see §2.)

#### Session cookie `secure=False` and no HSTS header (`medium`, `S`)
- **Evidence:** `routes_auth.py:186-191` sets `owl_session` with `secure=False`
  (comment reasons about the nginx↔uvicorn hop, but `secure` governs the
  browser↔origin connection, which is HTTPS); TTL 30 days. nginx has no
  `Strict-Transport-Security`; the primary block's HTTP→HTTPS `return 301` is
  commented out, redirect only via the certbot block.
- **Description:** `secure=False` lets the 30-day session cookie travel over any
  plaintext HTTP request the browser makes to the origin; with no HSTS, a first
  `http://` navigation (or an SSL-strip) exposes it before the redirect fires.
- **Recommendation:** `secure=True`; add
  `Strict-Transport-Security: max-age=31536000; includeSubDomains`; make the
  redirect unconditional.
- **Convergence:** REM terminates TLS at Traefik with HSTS by convention — a
  GoS-wide secure-cookie + HSTS baseline should apply to OWL.

#### No rate limit on magic-link send; tokens replayable within TTL (`medium`, `S`)
- **Evidence:** nginx rate-limits only `/video/*`, `/llm/*`, `/image/start` —
  `/auth/sign-in` falls to `location /` (connection cap only, no request-rate
  limit); no app-level throttle in `routes_auth.py:142`. `auth.py:206-210`
  documents the magic token is not stored/consumed, so it is usable repeatedly
  until the 15-min expiry.
- **Description:** An unauthenticated client can loop `POST /auth/sign-in` for a
  known member address, causing SMTP email-bombing from the shared Gmail sender;
  and an intercepted link (e.g. via the email-HTML injection above) replays for
  the full window.
- **Recommendation:** An nginx `limit_req` zone for `/auth/sign-in` plus a
  per-email cooldown; record consumed nonces in a small set for true single-use.

#### Member-tier custom ffmpeg args become arbitrary ffmpeg argv (`medium`, `M`)
- **Evidence:** `video.py:528-529` feeds a user template (with `{input}`/`{output}`
  substitution) into `subprocess.run` as a list; gated by `CUSTOM_PROMPT`
  (Member tier). No `shell=True` anywhere (good), but the argv is fully
  user-controlled and `{input}` is optional.
- **Description:** No shell injection, but a Member can pass any ffmpeg arguments —
  and ffmpeg exposes file/network protocols (`-i /etc/passwd`, http/concat inputs,
  arbitrary output paths), so this is an arbitrary file read/write and SSRF surface
  running as the service user. Limited to the semi-trusted Member tier, but a wide
  blast radius for an input-shaping feature.
- **Recommendation:** Constrain custom args to an allow-list of encoder/filter
  flags, reject protocol-bearing inputs and absolute output paths, force I/O into
  managed dirs; run transcodes under a restricted user or sandbox.
- **Convergence:** Containerising the transcode worker (REM-style) would bound this
  blast radius (CR-031).

#### Token and cookie cryptography is sound; path handling guarded (`positive`, `S`)
- **Evidence:** `auth.py` HMAC-SHA256 with `hmac.compare_digest`, purpose
  separation (login vs session, rejecting cross-use), expiry enforced;
  anti-enumeration identical response on sign-in; uuid4 share tokens; basename
  traversal guards in `uploads.py` and `routes_rem.py`. No `eval`/`exec`/`pickle`/
  `yaml.load`/`shell=True` in any of the 92 modules.
- **Caveats (verifier), not blocking the positive:** anti-enumeration is
  content-identical but not timing-identical (`send_magic_link` runs synchronously
  only for members — a latency oracle); the ephemeral `OWL_AUTH_SECRET` fallback
  silently invalidates all sessions on a prod misconfig (warn louder / refuse to
  serve gated tiers).

**Minor / refuted.** The dimension review offered a positive "capability spine
coverage is complete after the router split" — **refuted**: `routes_auth.py` is
4 routes / 3 `requires()`, and `POST /auth/sign-out` (`:195`) carries no
capability dependency. Practical impact is negligible (it only clears the cookie;
worst case CSRF-forced logout), so this is a `low`-severity gap, not a positive —
add `requires(PUBLIC_PAGE)` to restore the invariant (the existing route-walk test
waives it rather than failing). · No security headers beyond TLS (no CSP,
X-Content-Type-Options, X-Frame-Options, Referrer-Policy) on a service rendering
user-influenced HTML. · `members.json` file-permission expectations undocumented.

---

## 4. Refuted / materially adjusted findings (appendix)

Recorded so they are not rediscovered.

- **Security — "Capability spine coverage is complete across all 17 routers"
  (proposed `positive`) → refuted.** `routes_auth.py` is 4/3;
  `POST /auth/sign-out` is un-gated with no compensating middleware. Recast as a
  `low` finding (§3.9). The 94/95 count and the machine-enforced route-walk test
  (which *waives* sign-out) are the accurate framing.
- **Data — "No migration script exists anywhere in the repo" (sub-claim within
  the schema-version finding) → refuted.** `bin/anonymise-visitor-ips.py` is a
  self-described idempotent data migration that rewrites result JSONs in place.
  The parent finding (no schema version field, tolerant-reader-forever pattern)
  stands; the recommended backfill is *easier* than stated because the template
  exists.
- **Deployment — "nginx rate-limit drift" downgraded `medium` → `low`.** The
  mechanical drift is real (10+ submission endpoints uncovered), but
  `queue_control.enqueue` enforces a global depth cap of 8 and per-tier
  concurrent-job caps at the app layer, and 10 of the 12 uncovered endpoints are
  Member/Lab-gated. Queue-flood protection therefore does not depend on nginx; the
  residue is request-level load on the public `/rag/run` endpoints plus
  config-drift hygiene.
- **Reliability — "56 silent exception handlers" corrected to 76 handlers / 68
  with no diagnostics / 39 pure `pass`.** Severity unchanged (`high`); the
  corrected numbers are worse, not better.
- **Docs — "switch password added after the prior audit flagged the file"
  corrected.** The password commit (`d1941a3`, 2026-06-27) *predates* the
  2026-07-02 draft by five days; the reframing is that the draft's "no committed
  secrets" claim was wrong, not that the password was added in defiance.

---

## 5. Completeness-critique gaps

The final critic flagged issue classes no dimension reviewer raised. These were
**identified but not adversarially verified** — treat as leads to confirm.

1. **Dependency currency / supply chain unexamined** (security). `requirements.txt`
   is a 2026-04-10 snapshot with version-only pins, no hashes, no `pip-audit`/
   dependabot. `pillow==10.2.0` predates the fix for CVE-2024-28219;
   `requests==2.31.0` predates CVE-2024-35195/47081. Is anything in the stack
   currently vulnerable, and who would notice?
2. **No LICENSE file; AI-model/corpus license compliance never assessed** (docs).
   No `LICENSE` at all. The service publicly serves SD-Turbo/SDXL-Turbo image
   generation (Stability community/non-commercial licenses), plus Ollama weights
   and redistributed RAG corpus PDFs — applicability to a live member-facing org
   service was never posed.
3. **GDPR data-subject rights are aspirational** (data). Member identity is woven
   into results (`visitor_key 'm:<email>'`), `members.json`, nightly Nextcloud
   backups, and Gmail SMTP — at least two processors with no documented DPA.
   `routes_privacy.py:85` invites erasure requests by email, but no operational
   workflow scrubs an email from results JSON + uploads + backup history; an
   Art.17 request today is manual archaeology.
4. **The only logging the service does logs PII and secrets** (security).
   `email_send.py` logs the recipient member email on every send/failure and, in
   dry-run/staging, the complete magic link (a live bearer credential) to
   journald. Write a no-PII-in-logs convention *before* the planned logging pass
   multiplies this.
5. **Concurrency / race hazards in the job machinery never analysed**
   (reliability). `queue_control.py` has no `Lock` of any kind; `jobs` is mutated
   by the async worker, route handlers, and executor-thread job halves; the
   per-visitor cap is a check-then-act with no atomicity. `focus_mode_exit` is
   fired with the future discarded — an exception there silently leaves systemd
   units stopped. The measurement mutex is a fixed world-writable
   `/tmp/gos-measure.lock` (squattable).
6. **Disk-exhaustion vectors outside the uploads evictor** (data). Unmanaged:
   multipart spool to `/tmp`, the HuggingFace/Ollama model stores, the chromadb
   dir, journald/nginx logs. A full OS partition takes the service down harder
   than a full `results/`, and nothing monitors either. GPU OOM paths for
   member-triggered runs only sometimes reach `empty_cache()`.
7. **Wall-clock time is load-bearing for the science** (data). Energy integration
   uses `time.time()` (`power.py:269`), so an NTP step/slew mid-run skews the
   joule integration; ~75 naive `datetime` call sites vs 6 tz-aware, on a box that
   DST-shifts. `time.monotonic()` is the correct base for durations.
8. **Ollama is a load-bearing, unauthenticated, unpinned system dependency**
   (deployment). All LLM/RAG measurement drives `http://localhost:11434`
   (including destructive `unload_all_loaded_models`); Ollama is in no requirements
   or build provenance, its API has no auth, and CR-031 would have to carry it
   (plus ffmpeg, lm-sensors) into a container — none inventoried.
9. **Tapo plug threat model unexamined** (security). `power.py:73` builds the
   client from full TP-Link *cloud account* credentials in plaintext `.env`
   (backed up too). The P110s share the flat LAN; the KLAP handshake trusts
   whatever answers at `TAPO_P110_IP`, so an ARP-spoof/IP-squat can feed fabricated
   wattage into published findings (measurement integrity, not just
   confidentiality).
10. **Accessibility / i18n of the member UI: zero review** (testing). `ui.py:524`
    emits `<html>` with no `lang`; the only alt-text is two logos; no `aria-*`;
    ~5,100 lines of f-string page JS + canvas charts render live power with no text
    alternative or reduced-motion handling. For an EU-audience advocacy org the
    European Accessibility Act (enforceable since June 2025) makes this more than
    polish.

---

## 6. Ranked action plan

Ordered by (severity, effort). Security/data quick wins first, then structure.
Effort: S (<a day), M (a few days), L (a week+).

| # | Action | Effort | Resolves |
|---|---|---|---|
| 1 | `html.escape()` + allow-list `next`/`error`/`email` across the magic-link flow (`routes_auth.py`). | M | security-critical (XSS/open-redirect) |
| 2 | Gate `X-Real-IP` trust on the proxy address in `audience.py`/`queue_control.py`; bind uvicorn to `127.0.0.1`; firewall/document `:8000`. | M | security-high (tier spoof), CR-031 blocker |
| 3 | Rotate + remove the switch password from `GOS1_INFRA.md`; move identity/backup/personal material to a private ops note; scrub history. | S | docs-high, security (committed credential) |
| 4 | Extend the backup manifest to `members.json`/corpus/uploads/`rem_out` (encrypted); ship the last-success heartbeat into the watchdog or `/healthz`. | S | data-high (backup scope), data-medium (health check) |
| 5 | Add self-health fields to `/live` (or an ungated `/healthz`); point one external monitor at it; dead-man ping on the backup cron. | S | reliability-high (monitoring) |
| 6 | `secure=True` on the session cookie + HSTS in nginx + unconditional HTTP→HTTPS; add `requires(PUBLIC_PAGE)` to `/auth/sign-out`; nginx `limit_req` on `/auth/sign-in` + single-use nonces. | S | security-medium ×2, security-low (sign-out) |
| 7 | Commit the primary `wattlab.service` unit + `mount.conf` (and the backup cron line) into `systemd/`; fix the README source-of-truth claim. | S | deployment-high |
| 8 | One `OWL_ROOT`/`env.py`: env-derived paths + process-env-wins `.env` resolution across the ~25 hardcoded sites and 6 dotenv calls; `git rm --cached settings.json` + gitignore. | M | deployment-medium ×2, config-high, config-medium, editability-medium |
| 9 | Write the S54 JOURNAL/CLAUDE/ARCHITECTURE refresh (prepare-REM arc, module map, counts, CR-008 status); fix the dangling `REM/CLAUDE.md` link; bump `VERSION` + reconcile tags. | M | docs-medium ×2, editability-medium ×2 |
| 10 | Pre-push hook + `stage-on` running `pytest`; add skip markers / `tmp_path` routing so `pytest tests/` is green off-box; add `requirements-dev.txt` + `pytest.ini`. | M | testing-high, testing-medium, testing-low |
| 11 | Extract one `energy_wh()` helper (8 inline copies) with unit tests; add `llm`/`rag`/`image_gen` summarisation tests + anonymous-tier route smoke tests. | M | testing-medium ×2 |
| 12 | Add a module logger to each core module + one line per fail-soft handler (68 sites); append job failures with traceback to `job_failures.jsonl`; store `watts` age. | M | reliability-high ×2, reliability-medium |
| 13 | Inline-JS `node --check` pytest (S) now; begin per-page JS extraction and per-page template files (L) as pages are touched. | S→L | editability-medium, architecture-medium |
| 14 | Constrain / sandbox Member custom-ffmpeg argv; add `envelope_version` + a cooldown backfill using the existing migration script as template. | M | security-medium, data-medium |

Schedule once the above land: the completeness-gap leads (§5) — dependency
audit + `pip-audit` in CI, PII-in-logs convention before the logging pass, a
disk-space guard, `time.monotonic()` for energy integration, and a GDPR erasure
workflow — plus the shared GoS uptime monitor watching both REM and OWL.

---

*End of report.*
