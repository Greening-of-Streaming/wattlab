# data_exports — ad-hoc spreadsheet exports

## ForTania (video) — created 2026-05-29

Tania asked for all of **last night's `/video` runs** in one downloadable
spreadsheet, reachable from the open web via an unguessable ("hidden") link.

- **Generator / record:** `for_tania_video.py` — re-run to regenerate, or edit
  `NIGHT_START` / `NIGHT_END` / `COLUMNS` and re-run for modifications.
- **Canonical output:** `ForTania.csv` (124 rows = one per transcode; 22 runs:
  20 overnight `all_codecs` reps × 6 + 2 evening `both` runs × 2).
- **Public copy (hidden link):**
  `https://wattlab.greeningofstreaming.org/static/dl-9e58fc984c102e35/ForTania.csv`
  served on disk at `wattlab_service/static/dl-9e58fc984c102e35/ForTania.csv`.

### How the "hidden link" works
nginx serves `/static/` directly, **un-gated** (`access_log off`, no
`auth_request`) — so anyone with the URL can download it, no sign-in. Security
is by obscurity of the random `dl-…` subdir only. There is **no access log** for
it. To revoke: delete the `wattlab_service/static/dl-9e58fc984c102e35/` dir.

### To regenerate after new runs
```
python3 data_exports/for_tania_video.py
```
Writes the canonical CSV and (if the `dl-…` dir still exists) refreshes the
public copy.
