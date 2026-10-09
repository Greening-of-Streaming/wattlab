// Extracted from main.py (Phase 1, 2026-06-10) — see ARCHITECTURE.md.
(async function hydrateBenchEmbeds(){
  const els = document.querySelectorAll('.bench-embed');
  const renderers = {video: window.wlRenderVideoCard, llm: window.wlRenderLLMCard,
                     image: window.wlRenderImageCard, rag: window.wlRenderRAGCard};
  for (const el of els) {
    const type = el.dataset.type, kind = el.dataset.kind, jobId = el.dataset.resultId, bid = el.dataset.bid;
    const renderer = renderers[kind];
    const loading = el.querySelector('.loading');
    if (!renderer) { loading.textContent = 'no renderer for kind=' + kind; continue; }
    try {
      const r = await fetch('/benchmark/' + bid + '/result/' + type + '/' + jobId + '.json');
      if (r.status === 404 && el.dataset.host) {
        // A run measured on another node arrives by replication; its step
        // results can lag the run file by one pull.
        loading.textContent = type + '/' + jobId + ' not on this node yet — replicating from ' + el.dataset.host;
        continue;
      }
      if (!r.ok) { loading.textContent = 'could not load ' + type + '/' + jobId + ' (HTTP ' + r.status + ')'; continue; }
      const data = await r.json();
      el.innerHTML = renderer({result: data, isPrev: true, savedAt: data.saved_at});
    } catch(e) { loading.textContent = 'error: ' + e.message; }
  }
})();
