"""One-shot: does a MODERN aiowebostv connect to the C2 (secure/wss) with the
existing client_key? Writes a clear verdict to a file (survives ssh drops)."""
import asyncio
import subprocess
import sys

OUT = "/srv/data/owl/lg/libtest.txt"


def w(m):
    with open(OUT, "a") as f:
        f.write(m + "\n")
        f.flush()


def main():
    open(OUT, "w").close()
    VENV = "/tmp/lgtest/bin"
    subprocess.run(["python3", "-m", "venv", "/tmp/lgtest"], check=False)
    r = subprocess.run([f"{VENV}/pip", "install", "-q", "aiowebostv==0.8.0"],
                       capture_output=True, text=True)
    w(f"pip install rc={r.returncode} err={r.stderr.strip()[:200]}")
    ver = subprocess.run([f"{VENV}/python", "-c",
                          "import importlib.metadata as m;print(m.version('aiowebostv'))"],
                         capture_output=True, text=True).stdout.strip()
    w(f"installed aiowebostv version: {ver}")
    key = open("/srv/data/owl/lg/client_key").read().strip()
    probe = (
        "import asyncio\n"
        "from aiowebostv import WebOsClient\n"
        "import inspect\n"
        f"print('SIG', inspect.signature(WebOsClient.__init__))\n"
        "async def go(host):\n"
        "  for kw in [dict(client_key=%r, secure=True), dict(client_key=%r)]:\n"
        "    try:\n"
        "      c=WebOsClient(host, **kw)\n"
        "    except TypeError:\n"
        "      print(host,'no-secure-arg'); continue\n"
        "    try:\n"
        "      await asyncio.wait_for(c.connect(),15)\n"
        "      print(host,'CONNECTED secure=',kw.get('secure',False),'power=',(await c.get_power_state()))\n"
        "      await c.disconnect(); return\n"
        "    except Exception as e:\n"
        "      print(host,'secure=',kw.get('secure',False),'FAIL',type(e).__name__,str(e)[:70])\n"
        "      try:\n"
        "        await c.disconnect()\n"
        "      except Exception: pass\n"
        "asyncio.run(go('192.168.1.25'))\n"
        "asyncio.run(go('192.168.1.109'))\n"
    ) % (key, key)
    r2 = subprocess.run([f"{VENV}/python", "-c", probe],
                        capture_output=True, text=True)
    w("--- connect probe ---")
    w(r2.stdout.strip())
    if r2.stderr.strip():
        w("stderr: " + r2.stderr.strip()[:300])
    w("DONE")


if __name__ == "__main__":
    main()
