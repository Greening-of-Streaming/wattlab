"""
remote_panels.py — Lab-only "Other machines" panels for /llm and /image (CR-085).

Rendered from the hosts.py registry like the /video panel: one block per
enabled remote host, one button per runtime the host offers. The buttons act on
whatever the page already has selected (model, task) and hand the job id to the
page's own poller/renderer, so remote results display exactly like local ones —
with the machine named on the result. Hidden entirely without AI_REMOTE_RUN.
No main import (feature-module rule).
"""
import json

import audience
import hosts
from capabilities import AI_REMOTE_RUN, can

_STYLE = ('<style>.remote-btn{background:var(--panel-2);color:var(--text-1);border:1px solid var(--border-2);'
          'padding:0.3rem 0.6rem;font-size:0.78rem;cursor:pointer;font-family:inherit;margin:0.3rem 0.4rem 0 0}'
          '.remote-btn:hover{border-color:var(--accent)}.remote-btn:disabled{opacity:0.4;cursor:default}</style>')


# "Run on GoS1 also" (owner 2026-10-05): the companion job's status, GoS1's
# live wall power (so both machines' power is visible during a pair — the main
# progress widget shows the remote host's), and its result card when done.
# The queue is serial: the GoS1 job runs after the remote one; while it waits,
# the line shows GoS1 idling.
_PAIR_JS_T = """<script>
const OWL_ME = __ME__;
function owlPairRun(kind, jobId, renderCard) {
  let pair = document.getElementById('status-pair');
  if (!pair) {
    pair = document.createElement('div'); pair.id = 'status-pair'; pair.style.marginTop = '1.5rem';
    document.getElementById('status').after(pair);
  }
  const head = '<div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:0.5rem">' + OWL_ME + ' · same ' + ({llm: 'model + task', image: 'model + prompt', video: 'source + codec + engine'}[kind] || 'job') + '</div>';
  const t = setInterval(async () => {
    const [j, p] = await Promise.all([
      fetch('/' + kind + '/job/' + jobId).then(r => r.json()).catch(() => ({})),
      fetch('/power').then(r => r.json()).catch(() => ({}))]);
    if (j.result && (j.status === 'done' || j.stage === 'done' || kind === 'image')) {
      clearInterval(t); pair.innerHTML = head + renderCard({result: j.result, isPrev: false}); return;
    }
    if (j.error || j.status === 'error') {
      clearInterval(t); pair.innerHTML = head + '<div style="color:var(--err)">' + OWL_ME + ' run failed: ' + (j.error || '') + '</div>'; return;
    }
    const w = (p && p.watts != null) ? Number(p.watts).toFixed(1) + ' W' : '—';
    const st = j.stage === 'queued' ? 'queued' : (j.stage || 'starting');
    pair.innerHTML = head + '<div style="font-size:1.6rem;color:var(--accent);font-family:monospace;font-weight:bold">' + w + '</div>'
      + '<div style="color:var(--text-3);font-size:0.72rem">live wall power · ' + OWL_ME + ' · ' + st + '</div>';
  }, 2000);
}
</script>"""


def pair_js() -> str:
    return _PAIR_JS_T.replace("__ME__", json.dumps(hosts.local_label()))


def _pair_box(hid: str, what: str, simultaneous: bool = False) -> str:
    me = hosts.local_label()
    txt = f"Run on {me} at the same time ({what})" if simultaneous else f"Run on {me} also ({what})"
    return (f'<label style="color:var(--text-2);font-size:0.78rem;margin-left:0.5rem;cursor:pointer">'
            f'<input type="checkbox" id="also-local-{hid}"> {txt}</label>')


def offline_block(h: dict, hid: str) -> str:
    """CR-085: a host that does not answer is shown greyed, never waited on."""
    sub = " · ".join(x for x in (h.get("chip"), h.get("machine")) if x)
    return (f'<div class="batch-box" style="padding:0.75rem 1rem;margin-bottom:0.5rem;opacity:0.45">'
            f'<div style="color:var(--text-3);font-size:0.88rem;font-weight:bold">{h.get("label", hid)} '
            f'<span style="font-weight:normal;font-size:0.76rem">{sub}</span></div>'
            f'<div style="color:var(--text-4);font-size:0.75rem;margin-top:0.3rem">⏸ {h.get("label", hid)} is offline — '
            f'its engines are unavailable; everything on {hosts.local_label()} works as normal.</div></div>')


def peer_state(h: dict):
    """(is_peer, info_or_None). info None for a peer host = offline."""
    if hosts.driver(h) != "peer":
        return False, None
    import peer
    return True, peer.info({**h})


def _wrap(blocks: list, note: str) -> str:
    return ('<div id="remote-hosts-panel" style="margin:1rem 0 1.25rem 0">'
            '<div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;'
            'margin-bottom:0.5rem">Other machines <span style="color:var(--text-5);text-transform:none;'
            f'letter-spacing:0">· Lab only · {note}</span></div>' + _STYLE + "".join(blocks) + '</div>')


def _block(h: dict, hid: str, inner: str) -> str:
    sub = " · ".join(x for x in (h.get("chip"), h.get("machine")) if x)
    return (f'<div class="batch-box" style="padding:0.75rem 1rem;margin-bottom:0.5rem">'
            f'<div style="color:var(--accent);font-size:0.88rem;font-weight:bold">{h.get("label", hid)} '
            f'<span style="color:var(--text-3);font-weight:normal;font-size:0.76rem">{sub}</span></div>{inner}</div>')


def llm_panel_html(request) -> str:
    if not can(audience.tier(request), AI_REMOTE_RUN):
        return ""
    blocks, mlx = [], {}
    for hid, h in hosts.remote_hosts().items():
        is_peer, info = peer_state({**h, "id": hid})
        if is_peer and info is None:
            blocks.append(offline_block(h, hid))
            continue
        if is_peer:
            h = {**h, "ollama": bool(info.get("llm_models")),
                 "mlx_models": {m: True for m in info.get("mlx_models", [])}}
        btns = []
        if h.get("ollama"):
            btns.append(f'<button class="remote-btn" onclick="runRemoteLLM(\'{hid}\',\'ollama\')">'
                        f'Ollama (llama.cpp — same model file as {hosts.local_label()})</button>')
        if h.get("mlx_models"):
            mlx[hid] = sorted(h["mlx_models"])
            btns.append(f'<button class="remote-btn" data-mlx-host="{hid}" '
                        f'onclick="runRemoteLLM(\'{hid}\',\'mlx\')">MLX (Apple-native)</button>')
        if btns:
            btns.append(_pair_box(hid, "GPU, same model + task", simultaneous=is_peer))
            blocks.append(_block(h, hid, "".join(btns)))
    if not blocks:
        return ""
    js = f"""<script>
const _REMOTE_MLX = {json.dumps(mlx)};
function _syncRemoteMlx() {{
  document.querySelectorAll('[data-mlx-host]').forEach(b => {{
    const ok = (_REMOTE_MLX[b.dataset.mlxHost] || []).includes(selectedModel);
    b.disabled = !ok; b.title = ok ? '' : 'No MLX conversion registered for this model';
  }});
}}
document.addEventListener('click', () => setTimeout(_syncRemoteMlx, 0));
document.addEventListener('DOMContentLoaded', _syncRemoteMlx);
async function runRemoteLLM(host, runtime) {{
  const form = new FormData();
  form.append('host', host); form.append('model_key', selectedModel);
  form.append('task_key', selectedTask); form.append('runtime', runtime);
  const resp = await fetch('/llm/remote', {{method: 'POST', body: form}});
  const data = await resp.json().catch(() => ({{}}));
  if (data.job_id) {{
    document.getElementById('runBtn').disabled = true;
    startTime = Date.now(); renderProgress('baseline'); pollLLM(data.job_id);
    const also = document.getElementById('also-local-' + host);
    if (also && also.checked) {{
      const f2 = new FormData();
      f2.append('model_key', selectedModel); f2.append('task_key', selectedTask);
      f2.append('device', 'gpu');
      const d2 = await (await fetch('/llm/run', {{method: 'POST', body: f2}})).json().catch(() => ({{}}));
      if (d2.job_id) owlPairRun('llm', d2.job_id, wlRenderLLMCard);
    }}
  }} else {{
    document.getElementById('status').innerHTML = '<div style="color:var(--err)">Error: ' + (data.error || resp.status) + '</div>';
  }}
}}
</script>"""
    return _wrap(blocks, "runs the model + task selected above, cold start") + pair_js() + js


def image_panel_html(request) -> str:
    if not can(audience.tier(request), AI_REMOTE_RUN):
        return ""
    blocks = []
    for hid, h in hosts.remote_hosts().items():
        is_peer, info = peer_state({**h, "id": hid})
        if is_peer and info is None:
            blocks.append(offline_block(h, hid))
            continue
        if is_peer or h.get("python"):
            blocks.append(_block(h, hid, f'<button class="remote-btn" onclick="runRemoteImage(\'{hid}\')">'
                                         f'Generate on {h.get("label", hid)} GPU (same model files as {hosts.local_label()})</button>'
                                         + _pair_box(hid, "GPU", simultaneous=is_peer) +
                                         f'<div style="color:var(--text-4);font-size:0.72rem;margin-top:0.35rem">GPU path, clean method: model loaded '
                                         f'and warmed up first, 30 s settle, then ≥30 s of generation measured (~75 s per run). '
                                         f'Tick the box to run the same on {hosts.local_label()}\'s GPU for a like-for-like pair.</div>'))
    if not blocks:
        return ""
    js = """<script>
async function runRemoteImage(host) {
  // Clean method (owner 2026-10-05): warm-model session — load + warm-up
  // outside the window, 30 s settle, then ≥30 s of generation-only measurement.
  const SESSION = '&per_prompt=5&settle_s=30&target_s=30';
  let body = 'host=' + encodeURIComponent(host) + '&model_key=' + encodeURIComponent(selectedModelKey) + SESSION;
  // Send the prompt box like startMeasurement() does (bug 2026-10-05: the
  // remote button always fell back to the canonical prompt).
  const promptEl = document.getElementById('prompt');
  const prompt = promptEl ? promptEl.value.trim() : '';
  if (CAN_CUSTOM_PROMPT && prompt) body += '&prompt=' + encodeURIComponent(prompt);
  const resp = await fetch('/image/session', {method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: body});
  const data = await resp.json().catch(() => ({}));
  if (data.error || !data.job_id) { alert(data.error || ('HTTP ' + resp.status)); return; }
  document.getElementById('run-btn').disabled = true;
  imgStartTime = Date.now(); renderProgress('baseline', null, null);
  pollTimer = setInterval(() => pollJob(data.job_id), 1500);
  const also = document.getElementById('also-local-' + host);
  if (also && also.checked) {
    let b2 = 'host=local&model_key=' + encodeURIComponent(selectedModelKey) + SESSION;
    if (CAN_CUSTOM_PROMPT && prompt) b2 += '&prompt=' + encodeURIComponent(prompt);
    const d2 = await (await fetch('/image/session', {method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: b2})).json().catch(() => ({}));
    if (d2.job_id) owlPairRun('image', d2.job_id, wlRenderImageCard);
  }
}
</script>"""
    return _wrap(blocks, "runs the model + prompt selected above · warm-model session") + pair_js() + js
