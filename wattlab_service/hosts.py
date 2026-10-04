"""
hosts.py — compute-host registry (CR-085).

OWL runs on GoS1 ("the local host") and can drive other measurement machines
("remote hosts", GoS2 first) over SSH. Visitors pick *engines* (CPU · GPU ·
Apple media engine · …), never machines; the host is provenance stamped on
every result (decision D6, docs/gos2_design.md).

Everything about a remote machine lives in ONE settings entry under
`compute_hosts` — removing GoS2 or adding a GoS3 is a settings edit, no code:

    "compute_hosts": {
      "gos2": {
        "enabled": true,
        "label": "GoS2", "chip": "Apple M6", "machine": "Mac mini (Mac18,5)",
        "os": "macOS 27.0.1", "gpu_vendor": "apple",
        "ssh": "gos@192.168.1.29", "ssh_key": "/home/gos/.ssh/id_ed25519_gos2",
        "meters": ["192.168.1.165", "192.168.1.22"],     # [inner/primary, outer]
        "ffmpeg": "/opt/homebrew/bin/ffmpeg", "workdir": "owl",
        "engines": {
          "cpu": {"kind": "cpu", "label": "CPU (software)", "codecs": {
              "h264": {"encoder": "libx264", "args": [...]}, ...}},
          "hw":  {"kind": "hw",  "label": "Apple media engine", "codecs": {
              "h264": {"encoder": "h264_videotoolbox", "args": [...]}, ...}}
        }
      }
    }

Interim mechanism (owner, 2026-10-04): GoS1's service runs the remote encode
over SSH and reads the remote host's plugs directly over the LAN. Valid while
the machines share a LAN; the peer job API in docs/gos2_design.md §2 replaces
it before a host moves off-site.

Pre-CR-085 results carry no `host` field — every one of them was measured on
GoS1, so `result_host()` defaults to the local identity at read time (owner
decision: stored files are never rewritten).
"""

import hashlib
import shlex
import subprocess
from pathlib import Path

import settings as cfg

CODECS = ("h264", "h265", "av1")
CODEC_LABEL = {"h264": "H.264", "h265": "H.265", "av1": "AV1"}

# Identity of the machine this service runs on. Overridable via the
# `local_host` setting; the defaults describe GoS1.
_LOCAL_DEFAULT = {
    "id": "gos1",
    "label": "GoS1",
    "chip": "AMD Ryzen 9 7900 + NVIDIA RTX 5080",
    "machine": "Tower server",
    "os": "Ubuntu 24.04",
}

# SSH options for every remote call: key-only, never prompt, fail fast.
_SSH_OPTS = ["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
             "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=15"]


# --- Registry -----------------------------------------------------------------

def local_host() -> dict:
    s = cfg.load()
    return {**_LOCAL_DEFAULT, **(s.get("local_host") or {}), "remote": False}


def all_remote() -> dict:
    """Every configured remote host, enabled or not, keyed by id."""
    return dict(cfg.load().get("compute_hosts") or {})


def remote_hosts() -> dict:
    """Enabled remote hosts only — what the UI offers and the router accepts."""
    return {hid: h for hid, h in all_remote().items() if h.get("enabled", True)}


def get(host_id: str) -> dict | None:
    h = remote_hosts().get(host_id)
    return {**h, "id": host_id} if h else None


def engine(host: dict, engine_id: str) -> dict | None:
    return (host.get("engines") or {}).get(engine_id)


def codec_spec(host: dict, engine_id: str, codec: str) -> dict | None:
    e = engine(host, engine_id)
    return ((e or {}).get("codecs") or {}).get(codec)


def offered(host: dict) -> list:
    """[(engine_id, engine_label, kind, [codecs…]), …] in registry order — what
    the /video panel renders for this host."""
    out = []
    for eid, e in (host.get("engines") or {}).items():
        codecs = [c for c in CODECS if c in (e.get("codecs") or {})]
        if codecs:
            out.append((eid, e.get("label", eid), e.get("kind", "cpu"), codecs))
    return out


# --- Provenance (stamped on results; read-time default for old ones) -------------

def identity(host: dict) -> dict:
    """The `host` block stamped on a result."""
    return {k: host.get(k) for k in ("id", "label", "chip", "machine", "os")
            if host.get(k) is not None} | {"remote": bool(host.get("remote", True))}


def result_host(result: dict) -> dict:
    """Host that produced a stored result. Absent (every result saved before
    CR-085) = the local host, GoS1 — true by construction."""
    h = (result or {}).get("host")
    return h if isinstance(h, dict) and h.get("id") else identity(local_host())


def gpu_stamp(host: dict) -> dict:
    """Remote analogue of gpu.stamp() — persist must never stamp GoS1's GPU on
    a GoS2 result."""
    return {"vendor": host.get("gpu_vendor", "unknown"),
            "name": host.get("chip", host.get("label", "?")),
            "host": host.get("id")}


def power_stamp(host: dict) -> dict:
    """Remote analogue of power.stamp() — the host's own meters."""
    import power
    meters = host.get("meters") or []
    out = {"name": power.METER_NAME, "kind": power.METER_KIND,
           "resolution_s": power.METER_RESOLUTION_S, "host": host.get("id"),
           "meter_ips": list(meters)}
    if len(meters) >= 2:
        out.update({"meters": len(meters), "topology": "daisy_chain",
                    "stagger_s": power.METER_RESOLUTION_S / 2})
    return out


# --- SSH plumbing ---------------------------------------------------------------

def ssh_base(host: dict) -> list:
    cmd = ["ssh", *_SSH_OPTS]
    if host.get("ssh_key"):
        cmd += ["-i", host["ssh_key"]]
    return cmd + [host["ssh"]]


def run(host: dict, remote_cmd: str, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(ssh_base(host) + [remote_cmd], capture_output=True,
                          text=True, timeout=timeout)


def reachable(host: dict) -> bool:
    try:
        return run(host, "true", timeout=10).returncode == 0
    except Exception:
        return False


_SHA_CACHE: dict = {}


def local_sha256(path: Path) -> str:
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime)
    if key not in _SHA_CACHE:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _SHA_CACHE[key] = h.hexdigest()
    return _SHA_CACHE[key]


def ensure_input(host: dict, local_path: Path) -> dict:
    """Make sure the remote host holds a byte-identical copy of `local_path`
    under <workdir>/test_content/. Copies only when missing or different.
    Returns {rel, sha256, copied}. Raises on mismatch after copy — an engine
    comparison is only valid on identical input bytes."""
    local_path = Path(local_path)
    wd = host.get("workdir", "owl")
    rel = f"{wd}/test_content/{local_path.name}"
    sha = local_sha256(local_path)

    def remote_sha() -> str:
        r = run(host, f"shasum -a 256 {shlex.quote(rel)} 2>/dev/null | cut -d' ' -f1",
                timeout=300)
        return r.stdout.strip()

    copied = False
    if remote_sha() != sha:
        run(host, f"mkdir -p {shlex.quote(wd)}/test_content {shlex.quote(wd)}/out")
        scp = ["scp", "-q", *_SSH_OPTS]
        if host.get("ssh_key"):
            scp += ["-i", host["ssh_key"]]
        subprocess.run(scp + [str(local_path), f"{host['ssh']}:{rel}"],
                       check=True, timeout=3600)
        copied = True
        if remote_sha() != sha:
            raise RuntimeError(f"{host.get('label')}: input copy of {local_path.name} "
                               "does not match GoS1's bytes (sha256)")
    return {"rel": rel, "sha256": sha, "copied": copied}


def fetch(host: dict, remote_rel: str, local_path: Path) -> bool:
    scp = ["scp", "-q", *_SSH_OPTS]
    if host.get("ssh_key"):
        scp += ["-i", host["ssh_key"]]
    r = subprocess.run(scp + [f"{host['ssh']}:{remote_rel}", str(local_path)],
                       capture_output=True, timeout=600)
    return r.returncode == 0


def remote_ffmpeg_version(host: dict) -> str:
    try:
        r = run(host, f"{shlex.quote(host.get('ffmpeg', 'ffmpeg'))} -version | head -1",
                timeout=15)
        parts = r.stdout.split()
        return parts[2] if len(parts) > 2 else "unknown"
    except Exception:
        return "unknown"


def encode_cmd(host: dict, engine_id: str, codec: str, in_rel: str, out_rel: str,
               bps: int, gop: int) -> str:
    """Remote ffmpeg command string. Mirrors the GoS1 presets: ABR at the
    codec's configured bitrate, fixed GOP, scale to 1080p, AAC 128k — so the
    only variable between engines is the encoder itself. `{gop}` in a
    registry arg is substituted."""
    spec = codec_spec(host, engine_id, codec)
    if not spec:
        raise ValueError(f"{host.get('id')}/{engine_id} has no {codec} encoder")
    args = [str(a).replace("{gop}", str(gop)) for a in spec.get("args", [])]
    parts = [host.get("ffmpeg", "ffmpeg"), "-hide_banner", "-y", "-i", in_rel,
             "-c:v", spec["encoder"], "-b:v", f"{bps}k", *args,
             "-vf", "scale=-2:1080", "-c:a", "aac", "-b:a", "128k", out_rel]
    return shlex.join(parts)


# --- Engine on a result side (stamped on new GoS1 results; derived for old) -----

_CPU_ENCODER = {"h264": "libx264", "h265": "libx265", "av1": "libsvtav1"}


def codec_of_preset(key: str) -> str:
    k = key or ""
    return "h265" if "h265" in k else "av1" if "av1" in k else "h264"


def local_engine(preset_key: str, gpu_name: str | None = None,
                 gpu_encoder: str | None = None) -> dict:
    """Engine block for a GoS1 preset side. Hardware side = any key with
    'gpu' (cpu/gpu, h265_cpu/h265_gpu, av1_cpu/av1_gpu)."""
    codec = codec_of_preset(preset_key)
    if "gpu" in (preset_key or ""):
        return {"id": "gpu", "kind": "hw",
                "label": f"GPU ({gpu_name})" if gpu_name else "GPU",
                "encoder": gpu_encoder}
    return {"id": "cpu", "kind": "cpu", "label": "CPU (software)",
            "encoder": _CPU_ENCODER[codec]}


def side_engine(side: dict, result: dict | None = None) -> dict:
    """Engine that produced one side of a stored result. Pre-CR-085 sides
    carry no `engine`: derive it from the preset key and the result's own
    gpu_hardware stamp (never today's GPU — the box was AMD before 2026-05-29)."""
    if isinstance((side or {}).get("engine"), dict):
        return side["engine"]
    gh = (result or {}).get("gpu_hardware") or {}
    return local_engine((side or {}).get("preset_key", ""), gh.get("name"))
