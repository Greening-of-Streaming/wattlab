"""
owl_mlxgen.py — remote-side MLX LLM runner (CR-085 Part 3, Apple silicon only).

Second LLM environment on a Mac host, next to Ollama: `mlx-lm` runs the model
natively on Apple's unified-memory framework. Invoked over SSH by GoS1's
service (remote_ai.run_remote_llm with runtime="mlx"); measured exactly like the
Ollama path — a cold start (fresh process, model load counted), the same task
prompt, wall time from process start to last token — and prints ONE JSON line
with the same keys llm.run_inference_streaming returns.

Usage: python owl_mlxgen.py '<json args>'   args = {repo, prompt, max_tokens}
"""
import json
import sys
import time


def main():
    a = json.loads(sys.argv[1])
    # Timer starts with the runtime imported but the model NOT loaded — the
    # same state as Ollama's cold start (server up, model unloaded).
    from mlx_lm import load, stream_generate
    t_start = time.time()
    model, tok = load(a["repo"])
    t_load = time.time()
    msgs = [{"role": "user", "content": a["prompt"]}]
    prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False) \
        if getattr(tok, "chat_template", None) else a["prompt"]
    text, last = "", None
    for last in stream_generate(model, tok, prompt, max_tokens=int(a.get("max_tokens", 4096))):
        text += last.text
    t_end = time.time()
    out_tok = int(getattr(last, "generation_tokens", 0) or 0)
    in_tok = int(getattr(last, "prompt_tokens", 0) or 0)
    import mlx_lm
    print(json.dumps({
        "response": text,
        "prompt_tokens": in_tok, "output_tokens": out_tok,
        "total_tokens": in_tok + out_tok,
        "duration_s": round(t_end - t_start, 2),
        "load_s": round(t_load - t_start, 2),
        "tokens_per_sec": round(out_tok / max(t_end - t_start, 0.1), 1),
        "generation_tps": round(float(getattr(last, "generation_tps", 0) or 0), 1),
        "peak_memory_gb": round(float(getattr(last, "peak_memory", 0) or 0), 2),
        "runtime": "mlx-lm", "mlx_lm": getattr(mlx_lm, "__version__", "?"),
        "repo": a["repo"],
    }))


if __name__ == "__main__":
    main()
