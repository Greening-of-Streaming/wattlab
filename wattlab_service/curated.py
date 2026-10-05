"""
Curated content registry — canonical inputs the public/Anonymous path uses.

The route shape is:

    POST /image/start  prompt=<free text>     → gate(CUSTOM_PROMPT) → Member
    POST /image/start  prompt absent          → uses CANONICAL_IMAGE_PROMPT, Anonymous-OK

The /demo guided tour and any other Anonymous-tier surface call the same
endpoints but omit the free-text field; the route reads from this module
to pick the input. This keeps one URL per workload (no `/start-curated`
sibling) while still letting capabilities.gate() reject runtime input the
caller isn't allowed to provide.

Adding a row here is how you expose a new piece of pre-baked content to
the public path. Free-form variants live on the same route (which gates
CUSTOM_PROMPT / BATCH_COMPARE based on input presence).

This module deliberately has zero project-internal imports — it is
content config, like settings.json, not application logic.
"""

# Image generation — single canonical prompt for /demo step 3 and any other
# Anonymous-tier image generation. Picked for visual + thematic alignment with
# the GoS mission (energy / infrastructure / quiet) and short enough that
# SD-Turbo at 8 steps renders something coherent.
CANONICAL_IMAGE_PROMPT = "a lone wind turbine in an open landscape"

# CR-085 — /image/session prompt set (warm-model cross-host re-test, owner
# 2026-10-05). The canonical prompt plus three deliberately "hard" ones: a long
# multi-object scene (longer than CLIP's 77-token window on purpose — SD/SDXL
# truncate, SANA's Gemma encoder reads more), a text-rendering prompt, and a
# high-frequency texture. Diffusion compute is fixed by steps × resolution, so
# these are a CONTROL: per-prompt time/energy should not differ beyond noise.
IMAGE_SESSION_PROMPTS = [
    CANONICAL_IMAGE_PROMPT,
    ("a crowded night market in a rainy harbour city, dozens of food stalls with steaming woks, "
     "paper lanterns in red and gold, neon signs reflected in puddles, fishing boats moored behind, "
     "a tram crossing a stone bridge, people with umbrellas, a cat on a crate, mist over distant "
     "mountains, cinematic lighting, shallow depth of field, ultra detailed, 35mm photograph"),
    "a hand-painted wooden shop sign that reads 'GREENING OF STREAMING' above a bakery door",
    "extreme close-up of woven tweed fabric, individual fibres visible, macro photograph, sharp focus",
]

# RAG — canonical question for /demo step 4 (3-mode comparison) and any other
# Anonymous-tier RAG run. Tied to the corpus contents (codec / streaming
# energy papers) so the answer is corpus-grounded and the mode comparison
# means something.
CANONICAL_RAG_QUESTION = "How does codec choice affect streaming energy consumption?"

# Model used for any Anonymous-tier RAG run. Modern small (Qwen3 4B, Apr
# 2025) replaced the original Mistral 7B at the S30 ladder refresh: faster
# (typical ~2-3s), still corpus-faithful, and the 4B size point didn't
# exist when the original choice was made. TinyLlama is too noisy, Phi-4
# / mistral-nemo 12B are slow enough that a guided-tour visitor would bounce.
CANONICAL_RAG_MODEL = "qwen3:4b"
