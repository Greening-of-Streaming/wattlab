# Linode smoke test — run before sending the link to Akamai

Goal: prove that a stranger can go from `git clone` to a finished, stored
measurement on a plain cloud VM with no GPU and no meter (simulated power),
following only `container/README.md`.

## Results log

| Date | Where | Image | Smoke test | Notes |
|---|---|---|---|---|
| 2026-10-28 | GoS1, side port 8100, CPU image (no GPU passed) | owl:cpu 3.29 GB | 6/6 pass | video x264 🟢, qwen3.5:4b CPU 🟢, components + `focus_mode: unavailable` stored; fixed `/settings` 500 on GPU-less hosts |
| 2026-10-28 | GoS1, side port 8100, GPU override (RTX 5080) | owl:cu128 13.2 GB | manual | h264_nvenc encode 🟢, qwen3.5:4b on GPU 🟢, CPU-vs-GPU "both" run with VMAF (libx264 93.98 / nvenc 91.71, vmaf_v0.6.1); ladder fit S/M/L = gpu, XL = won't load |
| 2026-10-28 | Linode Dedicated 16 GB, Paris (8 vCPU AMD EPYC 7713, 15.6 GB, Ubuntu 24.04.4), code shipped by `git archive` of f6fc896 | owl:cpu 3.3 GB (+ ollama 9.4 GB); build + up 252 s | 6/6 pass, 283 s | first start fetched + verified all 3 sources, pulled S qwen3.5:4b (fit=cpu). Meridian libx264 153 s, 4.89 Wh simulated 🟢; qwen3.5:4b T1 on CPU 92.7 s, 2.89 Wh simulated 🟢; both stamped `simulated: True`, `focus_mode: unavailable`, components cpu/rest. From outside (GoS1): `/audience` 403, `POST /settings` 403, spoofed `X-Real-IP: 127.0.0.1` 403, GET `/settings` read-only (same as the public site). `OWL_POWER_SOURCE=component`: no powercap on the VM, so a red "Power source unavailable — RAPL: no readable … zones" strip and the job errors with that reason. Fixed a smoke-test false report (banner check under `pipefail`). Found + fixed: the node claimed to be GoS1 (heading, scope "Device layer only (GoS1)", host stamp `gos1` / Ryzen + RTX 5080) because the local-host defaults were GoS1's; it now detects its own identity (`OWL_NODE_LABEL`, else hostname, else "OWL node"; CPU/GPU/OS detected), and GoS1 pins its identity in settings.json like GoS2. Rebuilt: "OWL node" by default, "Linode Paris" / `linode-paris` / AMD EPYC 7713 with the label set. |

## 1. Create the instance (Ben, Linode Cloud Manager)

- **Plan:** Dedicated CPU 16 GB (8 vCPU), about $0.22/h. The Nanode that runs
  REM production is far too small; don't use it.
- **Image:** Ubuntu 24.04 LTS. **Region:** any (Paris is closest).
- **SSH key:** GoS1's `~/.ssh/id_ed25519.pub` (so the test can be driven from
  GoS1). Label it `owl-container-test`.
- Note the public IPv4 address.

## 2. Install Docker and get the code (from GoS1)

```bash
IP=<linode-ip>
ssh root@$IP 'curl -fsSL https://get.docker.com | sh'
# Before the branch is pushed: ship the working tree instead of cloning
git -C ~/wattlab archive --format=tar HEAD | ssh root@$IP 'mkdir -p /opt/wattlab && tar -x -C /opt/wattlab'
# After it is pushed:  ssh root@$IP 'git clone https://github.com/greeningofstreaming/wattlab /opt/wattlab'
```

## 3. Bring it up, exactly as the README says

```bash
ssh root@$IP 'cd /opt/wattlab && cp container/owl.env.example container/owl.env \
  && docker compose -f container/docker-compose.yml up -d --build'
ssh root@$IP 'cd /opt/wattlab && docker compose -f container/docker-compose.yml logs -f owl'   # until "Uvicorn running"
```

Expected on first start: three content files fetched and verified, tier S
(`qwen3.5:4b`, fit=cpu) pulled, the SIMULATED POWER strip on every page.

## 4. Smoke test

```bash
ssh root@$IP 'cd /opt/wattlab && container/smoke_test.sh'        # 6 checks, ~15 min on 8 vCPU
ssh -L 8000:localhost:8000 root@$IP                               # browse it: Lab via tunnel
```

Tier check from outside (briefly publish publicly, test, then revert):

```bash
ssh root@$IP 'cd /opt/wattlab && OWL_PUBLISH=8000 docker compose -f container/docker-compose.yml up -d owl'
ssh root@$IP "cd /opt/wattlab && OUTSIDE_URL=http://$IP:8000 container/smoke_test.sh"   # adds 2 Anonymous checks
# From GoS1 (outside): expect 404/403, never 200
curl -s -o /dev/null -w '%{http_code}\n' http://$IP:8000/audience
ssh root@$IP 'cd /opt/wattlab && docker compose -f container/docker-compose.yml up -d owl'   # back to loopback-only
```

Also try the component source to see how a VM without RAPL fails:

```bash
ssh root@$IP 'cd /opt/wattlab && echo OWL_POWER_SOURCE=component >> container/owl.env \
  && docker compose -f container/docker-compose.yml up -d owl'
# Expect: "Power source unavailable — RAPL: no readable … zones" strip; runs fail loudly.
```

## 5. Record, tear down, share

1. Add a row to the results log above (smoke-test output, image size, build time).
2. Tear down: `docker compose … down -v` (optional), then **delete the Linode**
   in Cloud Manager, which stops billing.
3. Tania/Ben sign-off, then send Akamai the link to `container/README.md`.
