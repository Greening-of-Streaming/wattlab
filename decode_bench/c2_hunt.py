"""c2_hunt.py — find the real C2 on the LAN, wake it, retest webOS.

Theory under test: every failing SSAP probe hit the TV in Always-Ready STANDBY
(plug ~10 W); yesterday's working connects were all screen-on. Also verify the
identity of whatever answers on .25/.109 (both now share one NEW Mac — could be
DHCP churn, not the TV).

Steps (all logged+flushed to /srv/data/owl/lg/hunt.txt):
  1. ping-sweep the /24, then scan the ARP table for the OLD TV MAC
     (ac:5a:f0:2f:b8:dc) and the NEW mystery MAC (20:28:bc:29:a0:e0).
  2. OUI-vendor lookup for both prefixes in any local database.
  3. SSDP M-SEARCH — LG/webOS devices answer with LOCATION; fetch the XML for
     friendlyName/modelName + true IP.
  4. Baseline Lab-E watts (~10 W = standby; 40 W+ = awake).
  5. Wake levers: raw WoL magic packets to BOTH MACs, wait, re-check watts;
     if still asleep, CEC-wake via the GTV (adb WAKEUP — SIMPLINK grabs the
     screen, proven in the 5-device run).
  6. Retest SSAP with the EXISTING key on .25, .109 and any SSDP-found IP.
"""
import asyncio
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.request

OUT = "/srv/data/owl/lg/hunt.txt"
OLD_MAC = "ac:5a:f0:2f:b8:dc"
NEW_MAC = "20:28:bc:29:a0:e0"
ADB = "/srv/data/owl/decode-bench/tools/platform-tools/adb"
GTV = "192.168.1.126:5555"
WATT_IP = "192.168.1.71"

sys.path.insert(0, "/home/gos/wattlab/wattlab_service")
os.chdir("/home/gos/wattlab/wattlab_service")


def log(m):
    with open(OUT, "a") as f:
        f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))
        f.flush()
        os.fsync(f.fileno())


def watts():
    try:
        import rig
        d = asyncio.run(rig.plug_status(WATT_IP))
        return round(d["watts"], 1)
    except Exception as e:
        return "ERR:%s" % type(e).__name__


async def _ping(ip, sem):
    async with sem:
        p = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", "1", ip,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await p.wait()


def sweep_and_arp():
    sem = asyncio.Semaphore(60)

    async def all_pings():
        await asyncio.gather(*[_ping("192.168.1.%d" % i, sem)
                               for i in range(1, 255)])
    asyncio.run(all_pings())
    hits = {"old": [], "new": []}
    for line in open("/proc/net/arp"):
        low = line.lower()
        if OLD_MAC in low:
            hits["old"].append(line.split()[0])
        if NEW_MAC in low:
            hits["new"].append(line.split()[0])
    log("ARP after sweep: OLD TV MAC %s at %s | NEW MAC %s at %s"
        % (OLD_MAC, hits["old"] or "NOWHERE", NEW_MAC, hits["new"]))
    return hits


def oui():
    dbs = ["/usr/share/nmap/nmap-mac-prefixes", "/usr/share/arp-scan/ieee-oui.txt",
           "/usr/share/hwdata/oui.txt", "/var/lib/ieee-data/oui.txt"]
    for db in dbs:
        if os.path.exists(db):
            for pfx, name in [("2028BC", "NEW"), ("AC5AF0", "OLD")]:
                try:
                    out = subprocess.run(["grep", "-i", pfx, db],
                                         capture_output=True, text=True,
                                         timeout=10).stdout.strip()[:120]
                    log("OUI %s (%s) in %s: %s" % (pfx, name, os.path.basename(db),
                                                   out or "no match"))
                except Exception:
                    pass
            return
    log("OUI: no local database found")


def ssdp():
    found = set()
    for st in ["ssdp:all", "urn:lge-com:service:webos-second-screen:1"]:
        msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
               "MAN: \"ssdp:discover\"\r\nMX: 2\r\nST: %s\r\n\r\n" % st).encode()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(3)
        try:
            s.sendto(msg, ("239.255.255.250", 1900))
            t0 = time.time()
            while time.time() - t0 < 4:
                try:
                    data, addr = s.recvfrom(4096)
                except socket.timeout:
                    break
                txt = data.decode(errors="replace")
                loc = next((l.split(":", 1)[1].strip() for l in txt.splitlines()
                            if l.lower().startswith("location:")), "")
                srv = next((l for l in txt.splitlines()
                            if l.lower().startswith("server:")), "")
                if loc and (addr[0], loc) not in found:
                    found.add((addr[0], loc))
                    tag = "webOS/LG" if ("webos" in txt.lower() or "lge" in txt.lower()) else ""
                    log("SSDP %s %s %s %s" % (addr[0], srv[:60], loc[:80], tag))
        except Exception as e:
            log("SSDP %s err %s" % (st, type(e).__name__))
        finally:
            s.close()
    # fetch XML descriptors for names
    for ip, loc in list(found)[:8]:
        try:
            xml = urllib.request.urlopen(loc, timeout=4).read().decode(errors="replace")
            fn = xml.split("<friendlyName>")[1].split("</friendlyName>")[0] if "<friendlyName>" in xml else "?"
            mn = xml.split("<modelName>")[1].split("</modelName>")[0] if "<modelName>" in xml else "?"
            log("SSDP-XML %s: friendlyName=%r model=%r" % (ip, fn[:40], mn[:40]))
        except Exception:
            pass
    return {ip for ip, _ in found}


def cert(ip):
    try:
        pem = ssl.get_server_certificate((ip, 3001), timeout=5)
        r = subprocess.run(["openssl", "x509", "-noout", "-subject", "-issuer"],
                           input=pem, capture_output=True, text=True, timeout=10)
        log("TLS cert %s:3001 → %s" % (ip, " | ".join(r.stdout.split("\n"))[:160]))
    except Exception as e:
        log("TLS cert %s:3001 err %s" % (ip, type(e).__name__))


def wol(mac):
    raw = bytes.fromhex(mac.replace(":", ""))
    pkt = b"\xff" * 6 + raw * 16
    for port in (9, 7):
        for dst in ("255.255.255.255", "192.168.1.255"):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                s.sendto(pkt, (dst, port))
                s.close()
            except Exception:
                pass


def ssap_test(ip):
    from aiowebostv import WebOsClient
    key = open("/srv/data/owl/lg/client_key").read().strip()

    async def go():
        c = WebOsClient(ip, client_key=key, connect_timeout=12)
        t = time.time()
        try:
            await c.connect()
            ps = await c.get_power_state()
            log("SSAP %s: CONNECTED (%.1fs) power=%s  ← WEBOS IS BACK" % (ip, time.time() - t, ps))
            return True
        except Exception as e:
            log("SSAP %s: %s %.1fs %s" % (ip, type(e).__name__, time.time() - t, str(e)[:60]))
            return False
        finally:
            try:
                await c.disconnect()
            except Exception:
                pass
    return asyncio.run(go())


def main():
    open(OUT, "w").close()
    log("C2 HUNT start — baseline Lab-E %s W" % watts())
    hits = sweep_and_arp()
    oui()
    ips = ssdp()
    cert("192.168.1.25")
    log("--- WAKE PHASE: WoL to both MACs ---")
    for _ in range(4):
        wol(OLD_MAC)
        wol(NEW_MAC)
        time.sleep(2)
    time.sleep(20)
    w1 = watts()
    log("post-WoL Lab-E %s W (10≈standby, 30+≈awake)" % w1)
    woke = isinstance(w1, float) and w1 > 20
    if not woke:
        log("WoL didn't wake it — trying CEC via GTV (adb WAKEUP; SIMPLINK grabs screen)")
        try:
            subprocess.run([ADB, "connect", GTV], capture_output=True, timeout=12)
            for _ in range(2):
                subprocess.run([ADB, "-s", GTV, "shell", "input", "keyevent",
                                "KEYCODE_WAKEUP"], capture_output=True, timeout=12)
                time.sleep(2)
            subprocess.run([ADB, "-s", GTV, "shell", "input", "keyevent",
                            "KEYCODE_HOME"], capture_output=True, timeout=12)
        except Exception as e:
            log("GTV CEC err %s" % type(e).__name__)
        time.sleep(20)
        w2 = watts()
        log("post-CEC Lab-E %s W" % w2)
    log("--- SSAP RETEST (existing key) ---")
    targets = ["192.168.1.25", "192.168.1.109"] + \
              [ip for ip in ips if ip not in ("192.168.1.25", "192.168.1.109")]
    for ip in targets[:6]:
        if ssap_test(ip):
            break
    log("final Lab-E %s W" % watts())
    log("DONE")


if __name__ == "__main__":
    main()
