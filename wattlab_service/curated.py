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
