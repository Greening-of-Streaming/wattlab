"""Primed C2 recovery listener (uses the SAME system aiowebostv OWL uses, so a
successful connect means OWL will recover too).

Each cycle, once external control is re-enabled on the TV:
  1. try the EXISTING key  -> if it connects, OWL is back (no pairing needed).
  2. else keyless pair      -> raises the on-screen 'allow?' prompt; on Accept,
                              saves the new key. OWL picks it up on its next poll.
While the setting is still OFF, both get 1008 and it just waits.
"""
import asyncio
import os
import tempfile
import time

from aiowebostv import WebOsClient

KEYFILE = "/srv/data/owl/lg/client_key"
STATUS = "/srv/data/owl/lg/pair_status.txt"
HOSTS = ["192.168.1.25", "192.168.1.109"]


def read_key():
    try:
        return open(KEYFILE).read().strip()
    except Exception:
        return None


def log(m):
    with open(STATUS, "a") as f:
        f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))
        f.flush()
        os.fsync(f.fileno())


async def try_existing(host):
    k = read_key()
    if not k:
        return False
    c = WebOsClient(host, client_key=k, connect_timeout=12)
    try:
        await c.connect()
        log("RECOVERED — existing key works on %s. OWL is back (native-decode OK)." % host)
        return True
    except Exception:
        return False
    finally:
        try:
            await c.disconnect()
        except Exception:
            pass


async def try_pair(host):
    c = WebOsClient(host, connect_timeout=45)   # keyless -> on-screen prompt
    try:
        await c.connect()
        nk = getattr(c, "client_key", None)
        if nk and len(nk) > 10:
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(KEYFILE))
            os.write(fd, nk.encode())
            os.close(fd)
            os.replace(tmp, KEYFILE)
            log("PAIRED via %s — new key saved. OWL is back." % host)
            return True
    except Exception as e:
        log("%s: waiting (%s)" % (host, type(e).__name__))
    finally:
        try:
            await c.disconnect()
        except Exception:
            pass
    return False


def main():
    log("PRIMED — waiting for the external-control setting to be re-enabled on the C2")
    t0 = time.time()
    while time.time() - t0 < 12 * 3600:
        for h in HOSTS:
            if asyncio.run(try_existing(h)):
                return
        for h in HOSTS:
            if asyncio.run(try_pair(h)):
                return
        time.sleep(8)
    log("listener timed out (12h) — relaunch if still needed")


if __name__ == "__main__":
    main()
