"""
env.py — the ONE .env loader (CR-031 §3 pre-work item 1 / CR-085 Phase 1).

Returns the .env values with the process environment taking precedence for any
key the file defines or OWL knows about — so a launchd/systemd `Environment=`
or a container can inject secrets without editing the file. Replaces the five
modules that each read "/home/gos/wattlab/.env" directly.
"""
import os
from dotenv import dotenv_values

import paths

_KNOWN_PREFIXES = ("TAPO_", "OWL_", "ELECTRICITYMAPS_")


def load() -> dict:
    values = dict(dotenv_values(paths.ENV_FILE))
    for k, v in os.environ.items():
        if k in values or k.startswith(_KNOWN_PREFIXES):
            values[k] = v
    return values
