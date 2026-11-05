#!/usr/bin/env python3
# Synthetic disk job, run ON GoS2. usage: gos2_io.py PATH prep|read|write RATE_MB_S(0=flat) SECONDS FILE_GIB
# Cache bypassed (F_NOCACHE, read-ahead off), 1 MiB sequential, wraps inside the file, incompressible data.
import fcntl, json, mmap, os, resource, sys, time
path, op, rate, secs, gib = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5])
BS, POOL, SIZE = 1 << 20, 64 << 20, gib << 30
buf = mmap.mmap(-1, POOL); mv = memoryview(buf)
if op in ("prep", "write"):
    with open("/dev/urandom", "rb") as f: buf[:] = f.read(POOL)
fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
fcntl.fcntl(fd, 48, 1)   # F_NOCACHE
fcntl.fcntl(fd, 45, 0)   # F_RDAHEAD off
n, pos, off, t0 = 0, 0, 0, time.monotonic()
while True:
    now = time.monotonic()
    if op == "prep":
        if pos >= SIZE: break
    elif now - t0 >= secs: break
    if rate:
        wait = t0 + n * BS / (rate * 1e6) - now
        if wait > 0: time.sleep(wait)
    if op == "read":
        got = os.readv(fd, [mv[:BS]])
        if got < BS:
            os.lseek(fd, 0, 0); pos = 0
            if got == 0: continue
    else:
        if pos >= SIZE: os.lseek(fd, 0, 0); pos = 0
        got = os.write(fd, mv[off:off + BS]); off = (off + BS) % POOL
    pos += got; n += 1
if op != "read": fcntl.fcntl(fd, 51)   # F_FULLFSYNC
dt = time.monotonic() - t0
u = resource.getrusage(resource.RUSAGE_SELF)
print(json.dumps({"op": op, "bytes": n * BS, "secs": round(dt, 2), "mb_s": round(n * BS / 1e6 / dt, 1),
                  "cpu_user_s": round(u.ru_utime, 2), "cpu_sys_s": round(u.ru_stime, 2)}))
