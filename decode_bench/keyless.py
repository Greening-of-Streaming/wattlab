"""Keyless connect probe (aiowebostv 0.8.0 in /tmp/lgtest). Distinguishes:
  immediate 1008  -> external-control permission is OFF (Settings toggle needed)
  ~35s timeout    -> pairing prompt is showing (key invalidated; a re-pair Accept fixes it)
Writes verdict to /srv/data/owl/lg/keyless.txt."""
import asyncio
import time

from aiowebostv import WebOsClient

OUT = "/srv/data/owl/lg/keyless.txt"


def w(m):
    with open(OUT, "a") as f:
        f.write(m + "\n"); f.flush()


async def go(host):
    c = WebOsClient(host, connect_timeout=35)   # long, to catch a pairing wait
    t = time.time()
    try:
        await c.connect()
        w(f"{host}: CONNECTED keyless in {time.time()-t:.1f}s key={getattr(c,'client_key','?')}")
    except Exception as e:
        w(f"{host}: {type(e).__name__} after {time.time()-t:.1f}s :: {str(e)[:70]}")
    finally:
        try:
            await c.disconnect()
        except Exception:
            pass


open(OUT, "w").close()
w("keyless probe start")
asyncio.run(go("192.168.1.25"))
w("DONE")
