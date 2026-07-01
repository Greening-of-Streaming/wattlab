"""
routes_finding_draft.py — Lab-only LLM-assisted finding drafter (CREATE_FINDING).

Three routes, all Lab-gated:
  GET  /findings/draft            — operator UI: pick result ids → draft → edit → save
  POST /findings/draft            — run the model, return draft + validation (no write)
  POST /findings/draft/save       — write the operator-edited markdown to docs/findings/

Human-in-the-loop by construction: POST /draft never touches disk; only
/draft/save writes, and it re-validates and round-trips through the canonical
findings loader first. See finding_draft.py for the engine and guardrails.

Feature-flagged with the rest of the catalog via settings.findings_enabled
(the drafter is meaningless without the catalog it feeds).
"""
import html as html_lib

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

import finding_draft
import settings as cfg
import ui
from capabilities import requires, CREATE_FINDING

router = APIRouter()


def _enabled() -> bool:
    return bool(cfg.load().get("findings_enabled", False))


@router.post("/findings/draft", dependencies=[Depends(requires(CREATE_FINDING))])
async def draft(request: Request):
    if not _enabled():
        return JSONResponse({"error": "findings disabled"}, status_code=404)
    body = await request.json()
    ids = [str(x).strip() for x in (body.get("source_result_ids") or []) if str(x).strip()]
    if not ids:
        return JSONResponse({"error": "source_result_ids required"}, status_code=400)
    model = str(body.get("model") or finding_draft.DEFAULT_MODEL)
    angle = str(body.get("angle") or "")
    try:
        result = finding_draft.draft_finding(ids, model=model, angle=angle)
    except finding_draft.DraftError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    return JSONResponse(result)


@router.post("/findings/draft/save",
             dependencies=[Depends(requires(CREATE_FINDING))])
async def draft_save(request: Request):
    if not _enabled():
        return JSONResponse({"error": "findings disabled"}, status_code=404)
    body = await request.json()
    meta = body.get("meta") or {}
    md_body = str(body.get("body_md") or "")
    if not meta or not md_body:
        return JSONResponse({"error": "meta and body_md required"}, status_code=400)
    try:
        path = finding_draft.save_draft(meta, md_body)
    except finding_draft.DraftError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    return JSONResponse({"ok": True, "slug": meta.get("slug"),
                         "url": f"/findings/{meta.get('slug')}",
                         "path": str(path)})


@router.get("/findings/draft", response_class=HTMLResponse,
            dependencies=[Depends(requires(CREATE_FINDING))])
async def draft_page(request: Request):
    if not _enabled():
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    return ui.render_page(request, "Draft a finding (Lab)",
                          styles=_STYLES, body=_BODY)


_STYLES = """
.fd-wrap{max-width:860px;margin:0 auto;padding:1rem}
.fd-wrap textarea,.fd-wrap input{width:100%;background:#111;color:#eee;
  border:1px solid #333;border-radius:6px;padding:.5rem;font-family:inherit}
.fd-wrap textarea{min-height:8rem;font-family:monospace;font-size:.85rem}
.fd-row{margin:.8rem 0}
.fd-issues .err{color:#ff6b6b}.fd-issues .warn{color:#ffd166}
.fd-note{color:#888;font-size:.85rem}
button.fd-btn{background:#00ff99;color:#000;border:0;border-radius:6px;
  padding:.55rem 1rem;font-weight:600;cursor:pointer}
button.fd-btn[disabled]{opacity:.4;cursor:not-allowed}
"""

# Deliberately minimal vanilla JS — drives the two POST endpoints. Operator
# pastes result ids, drafts, edits the prose, then saves. Save stays disabled
# until a draft with no blocking errors is produced.
_BODY = """
<div class="fd-wrap">
  <h1>Draft a finding <span class="fd-note">· Lab · AI-assisted, human-gated</span></h1>
  <p class="fd-note">The model proposes; you edit and approve. It cannot set
  confidence, scope, or the cited sources — those come from the measurements.
  Nothing is published until you press Save.</p>

  <div class="fd-row">
    <label>Source result ids (comma or newline separated, e.g. <code>video/e18a9d57</code>)</label>
    <textarea id="fd-ids" style="min-height:4rem"></textarea>
    <p class="fd-note">Use the result <b>type</b> as the prefix (the storage type,
    not the page name) — e.g. <code>enhance/8675abb9</code>, not
    <code>enhance-run/…</code>. A page-name slip is auto-corrected when the id is
    unambiguous.</p>
  </div>
  <div class="fd-row">
    <label>Angle / focus <span class="fd-note">(optional — steers the write-up)</span></label>
    <textarea id="fd-angle" style="min-height:3rem"
      placeholder="e.g. Lead with the quality improvement (VQA/resolution) and frame energy as the budget that bought it — what you get for your energy spend."></textarea>
  </div>
  <div class="fd-row">
    <button class="fd-btn" id="fd-draft">Draft with model</button>
    <span class="fd-note" id="fd-status"></span>
  </div>

  <div class="fd-row"><label>Headline</label><input id="fd-headline"></div>
  <div class="fd-row"><label>Claim (short)</label><input id="fd-claim"></div>
  <div class="fd-row"><label>Body (markdown)</label><textarea id="fd-bodymd"></textarea></div>
  <div class="fd-row fd-note">
    confidence: <b id="fd-conf">—</b> · scope: <span id="fd-scope">—</span>
  </div>
  <div class="fd-row fd-issues" id="fd-issues"></div>

  <div class="fd-row">
    <button class="fd-btn" id="fd-save" disabled>Save finding</button>
  </div>
</div>
<script>
(function(){
  var draft=null;
  function ids(){return document.getElementById('fd-ids').value
    .split(/[\\n,]+/).map(function(s){return s.trim()}).filter(Boolean);}
  function showIssues(list){
    var el=document.getElementById('fd-issues');
    el.innerHTML=(list||[]).map(function(i){
      return '<div class="'+(i.severity==='error'?'err':'warn')+'">'+
        (i.severity==='error'?'✗ ':'⚠ ')+i.message+'</div>';}).join('');
  }
  document.getElementById('fd-draft').onclick=function(){
    var st=document.getElementById('fd-status'); st.textContent='drafting…';
    var angle=document.getElementById('fd-angle').value;
    fetch('/findings/draft',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({source_result_ids:ids(),angle:angle})})
      .then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j}})})
      .then(function(res){
        if(!res.ok){st.textContent='error: '+(res.j.error||'failed');return;}
        draft=res.j; var d=draft.draft;
        document.getElementById('fd-headline').value=d.headline||'';
        document.getElementById('fd-claim').value=d.claim_short||'';
        document.getElementById('fd-bodymd').value=d.body_md||'';
        document.getElementById('fd-conf').textContent=d.confidence;
        document.getElementById('fd-scope').textContent=d.scope;
        showIssues(draft.validation);
        document.getElementById('fd-save').disabled=!draft.ok;
        st.textContent=draft.ok?'draft ready — review & edit':'draft has blocking errors';
      }).catch(function(e){st.textContent='error: '+e;});
  };
  document.getElementById('fd-save').onclick=function(){
    if(!draft)return; var st=document.getElementById('fd-status');
    var meta=Object.assign({},draft.draft);
    meta.headline=document.getElementById('fd-headline').value;
    meta.claim_short=document.getElementById('fd-claim').value;
    var bodymd=document.getElementById('fd-bodymd').value;
    delete meta.body_md;
    fetch('/findings/draft/save',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({meta:meta,body_md:bodymd})})
      .then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j}})})
      .then(function(res){
        if(!res.ok){st.textContent='save failed: '+(res.j.error||'');return;}
        st.innerHTML='saved → <a href="'+res.j.url+'">'+res.j.url+'</a>';
      });
  };
})();
</script>
"""
