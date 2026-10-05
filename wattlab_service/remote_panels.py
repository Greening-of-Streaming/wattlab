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
_PAIR_JS = """<script>
function owlPairRun(kind, jobId, renderCard) {
  let pair = document.getElementById('status-pair');
  if (!pair) {
    pair = document.createElement('div'); pair.id = 'status-pair'; pair.style.marginTop = '1.5rem';
    document.getElementById('status').after(pair);
  }
  const head = '<div style="color:var(--text-3);font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:0.5rem">GoS1 · same model + ' + (kind === 'llm' ? 'task' : 'prompt') + '</div>';
  const t = setInterval(async () => {
    const [j, p] = await Promise.all([
      fetch('/' + kind + '/job/' + jobId).then(r => r.json()).catch(() => ({})),
      fetch('/power').then(r => r.json()).catch(() => ({}))]);
    if (j.result && (j.status === 'done' || j.stage === 'done' || kind === 'image')) {
      clearInterval(t); pair.innerHTML = head + renderCard({result: j.result, isPrev: false}); return;
    }
    if (j.error || j.status === 'error') {
      clearInterval(t); pair.innerHTML = head + '<div style="color:var(--err)">GoS1 run failed: ' + (j.error || '') + '</div>'; return;
    }
    const w = (p && p.watts != null) ? Number(p.watts).toFixed(1) + ' W' : '—';
    const st = j.stage === 'queued' ? 'queued (runs after the remote job)' : (j.stage || 'starting');
    pair.innerHTML = head + '<div style="font-size:1.6rem;color:var(--accent);font-family:monospace;font-weight:bold">' + w + '</div>'
      + '<div style="color:var(--text-3);font-size:0.72rem">live wall power · GoS1 · ' + st + '</div>';
  }, 2000);
}
</script>"""


def _pair_box(hid: str, what: str) -> str:
    return (f'<label style="color:var(--text-2);font-size:0.78rem;margin-left:0.5rem;cursor:pointer">'
            f'<input type="checkbox" id="also-local-{hid}"> Run on GoS1 also ({what})</label>')


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
        btns = []
        if h.get("ollama"):
            btns.append(f'<button class="remote-btn" onclick="runRemoteLLM(\'{hid}\',\'ollama\')">'
                        f'Ollama (llama.cpp — same model file as GoS1)</button>')
        if h.get("mlx_models"):
            mlx[hid] = sorted(h["mlx_models"])
            btns.append(f'<button class="remote-btn" data-mlx-host="{hid}" '
                        f'onclick="runRemoteLLM(\'{hid}\',\'mlx\')">MLX (Apple-native)</button>')
        if btns:
            btns.append(_pair_box(hid, "GPU, same model + task"))
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
    return _wrap(blocks, "runs the model + task selected above, cold start") + _PAIR_JS + js


def image_panel_html(request) -> str:
    if not can(audience.tier(request), AI_REMOTE_RUN):
        return ""
    blocks = []
    for hid, h in hosts.remote_hosts().items():
        if h.get("python"):
            blocks.append(_block(h, hid, f'<button class="remote-btn" onclick="runRemoteImage(\'{hid}\')">'
                                         f'Generate on {h.get("label", hid)} GPU (same model files as GoS1)</button>'
                                         + _pair_box(hid, "GPU") +
                                         f'<div style="color:var(--text-4);font-size:0.72rem;margin-top:0.35rem">Always the GPU path. '
                                         f'Tick the box to queue the same model + prompt on GoS1\'s GPU for a like-for-like pair '
                                         f'(the page\'s own default is CPU).</div>'))
    if not blocks:
        return ""
    js = """<script>
async function runRemoteImage(host) {
  let body = 'host=' + encodeURIComponent(host) + '&model_key=' + encodeURIComponent(selectedModelKey);
  // Send the prompt box like startMeasurement() does (bug 2026-10-05: the
  // remote button always fell back to the canonical prompt).
  const promptEl = document.getElementById('prompt');
  const prompt = promptEl ? promptEl.value.trim() : '';
  if (CAN_CUSTOM_PROMPT && prompt) body += '&prompt=' + encodeURIComponent(prompt);
  const resp = await fetch('/image/remote', {method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: body});
  const data = await resp.json().catch(() => ({}));
  if (data.error || !data.job_id) { alert(data.error || ('HTTP ' + resp.status)); return; }
  document.getElementById('run-btn').disabled = true;
  imgStartTime = Date.now(); renderProgress('baseline', null, null);
  pollTimer = setInterval(() => pollJob(data.job_id), 1500);
  const also = document.getElementById('also-local-' + host);
  if (also && also.checked) {
    let b2 = 'device=gpu&model_key=' + encodeURIComponent(selectedModelKey);
    if (CAN_CUSTOM_PROMPT && prompt) b2 += '&prompt=' + encodeURIComponent(prompt);
    const d2 = await (await fetch('/image/start', {method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: b2})).json().catch(() => ({}));
    if (d2.job_id) owlPairRun('image', d2.job_id, wlRenderImageCard);
  }
}
</script>"""
    return _wrap(blocks, "runs the model + prompt selected above on the GPU path") + _PAIR_JS + js
