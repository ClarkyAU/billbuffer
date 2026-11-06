#!/usr/bin/env python3
"""Server checks that need no browser: addresses, bad requests, timeouts, compression, the script rule,
recovering a corrupt save, history, and symlinks. Run: python3 tests/server_test.py"""
import base64
import gzip
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = 0


def ok(cond, text):
    global fails
    if not cond:
        fails += 1
    print(("  ok " if cond else "  FAIL ") + text)


def start(data, port, **env):
    e = dict(os.environ, BB_DATA=data, BB_PORT=str(port), BB_PASSCODE="", BB_TIMEOUT="2", **env)
    p = subprocess.Popen([sys.executable, "-u", os.path.join(ROOT, "server.py")], env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            return p
        except OSError:
            time.sleep(0.1)
    raise SystemExit("server did not start: " + p.stdout.read())


def req(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Host": "127.0.0.1:%d" % port}
    h.update(headers or {})
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, dict((k.lower(), v) for k, v in r.getheaders()), data


def new_dir():
    base = tempfile.mkdtemp(prefix="bb-test-")
    os.chmod(base, 0o755)  # the server drops to an unprivileged user and must reach its data
    return base, os.path.join(base, "data")


def stamp(seconds_ago):
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time() - seconds_ago))


base, data = new_dir()
PORT = 8301
srv = start(data, PORT)
try:
    print("addresses")
    for host in ("192.168.1.20:47219", "truenas:47219", "nas.local:47219", "box.tail1234.ts.net", "[::1]:8080", "localhost:8080"):
        ok(req(PORT, "GET", "/", headers={"Host": host})[0] == 200, "answers " + host)
    s, h, b = req(PORT, "GET", "/", headers={"Host": "evil.example:47219"})
    ok(s == 403 and b"BB_HOSTS" in b, "refuses another site's name and says how to allow it")
    s, h, b = req(PORT, "PUT", "/api/state", json.dumps({"base": 0, "state": {"bills": []}}),
                  {"Host": "evil.example:47219", "Origin": "http://evil.example:47219", "Content-Type": "application/json"})
    ok(s == 403 and not os.path.exists(os.path.join(data, "state.json")), "a rebinding-style write is refused")

    print("bad requests")
    ok(req(PORT, "PUT", "/api/state", "[1]", {"Content-Type": "application/json"})[0] == 400, "a list instead of an object is a 400")
    ok(req(PORT, "PUT", "/api/state", b"\xff\xfe", {"Content-Type": "application/json"})[0] == 400, "bytes that aren't text are a 400")
    ok(req(PORT, "POST", "/api/login", "", {"Content-Length": "abc"})[0] == 400, "a non-number length is a 400")
    ok(req(PORT, "POST", "/api/login", json.dumps({"passcode": "x" * 5000}), {"Content-Type": "application/json"})[0] == 413, "an oversized sign-in is refused")
    ok(req(PORT, "GET", "/api/status")[0] == 200, "still answering after all that")

    print("quiet connections")
    sock = socket.create_connection(("127.0.0.1", PORT))
    sock.send(b"GET / HTTP/1.1\r\n")
    sock.settimeout(5)
    t = time.time()
    try:
        closed = sock.recv(10) == b""
    except socket.timeout:
        closed = False
    ok(closed and time.time() - t < 4.5, "a connection that goes quiet is closed")
    sock.close()

    print("page delivery")
    page = open(os.path.join(ROOT, "site", "index.html"), "rb").read()
    s, h, b = req(PORT, "GET", "/", headers={"Accept-Encoding": "gzip, br"})
    ok(h.get("content-encoding") == "gzip" and gzip.decompress(b) == page, "page is sent compressed (%d KB instead of %d KB)" % (len(b) // 1024, len(page) // 1024))
    s2, h2, b2 = req(PORT, "GET", "/", headers={"Accept-Encoding": "gzip", "If-None-Match": h["etag"]})
    ok(s2 == 304 and not b2, "an unchanged page is not sent again")
    s3, h3, b3 = req(PORT, "GET", "/")
    ok(b3 == page and "content-encoding" not in h3 and h3["etag"] != h["etag"], "browsers without gzip get it plain")
    ok(req(PORT, "GET", "/fonts/onest.woff2", headers={"Accept-Encoding": "gzip"})[1].get("content-encoding") is None, "fonts are not compressed again")
    script = re.search(rb"<script>(.*?)</script>", page, re.S).group(1)
    want = "'sha256-%s'" % base64.b64encode(hashlib.sha256(script).digest()).decode()
    csp = h["content-security-policy"]
    script_src = re.search(r"script-src ([^;]*)", csp).group(1)
    ok(want in script_src and "unsafe-inline" not in script_src, "only the app's own script may run")
    ok(req(PORT, "GET", "/missing.png")[0] == 404 and req(PORT, "GET", "/some/page")[0] == 200, "missing files are 404, other paths open the app")

    print("saves and history")
    v = 0
    for i in range(3):
        s, h, b = req(PORT, "PUT", "/api/state", json.dumps({"base": v, "state": {"bills": [], "n": i}}), {"Content-Type": "application/json"})
        v = json.loads(b)["version"]
    s, h, b = req(PORT, "GET", "/api/state")
    ok(json.loads(b)["state"]["n"] == 2 and json.loads(open(os.path.join(data, "state.json")).read())["version"] == v, "saves are served and written to disk")
    ok(req(PORT, "GET", "/api/state?since=%d" % v)[2] == b'{"version":%d,"unchanged":true}' % v, "an unchanged copy is not sent again")
finally:
    srv.terminate()
    srv.wait()

print("history kept by time")
hist = os.path.join(data, "history")
for f in os.listdir(hist):
    os.remove(os.path.join(hist, f))
t3 = time.time() - 3 * 86400
t3 = t3 - (t3 % 3600) + 1200  # twenty past an hour, three days ago
plan = [(time.time() - (t3 + 60 * k), 10 + k) for k in range(5)]  # five saves that hour; v14 is the latest
plan += [(40 * 86400, 1), (35 * 86400, 2)]  # older than 30 days
plan += [(600 + k, 100 + k) for k in range(15)]  # fifteen saves in the last few minutes; v100 is the newest
for ago, ver in plan:
    with open(os.path.join(hist, "state-%s-v%d.json" % (stamp(ago), ver)), "w") as f:
        json.dump({"version": ver, "state": {"bills": [], "v": ver}}, f)
srv = start(data, PORT)
try:
    s, h, b = req(PORT, "GET", "/api/state")
    cur = json.loads(b)["version"]
    req(PORT, "PUT", "/api/state", json.dumps({"base": cur, "state": {"bills": []}}), {"Content-Type": "application/json"})
finally:
    srv.terminate()
    srv.wait()
names = sorted(os.listdir(hist))
vers = [int(re.search(r"-v(\d+)\.json", n).group(1)) for n in names]
ok(not any(v in (1, 2) for v in vers), "copies older than 30 days are removed")
ok([v for v in vers if 10 <= v <= 14] == [14], "one copy kept for a day three days ago (the latest)")
ok(all(v in vers for v in range(100, 109)) and 114 not in vers, "the most recent saves are all kept (%d files in total)" % len(names))

print("unreadable save")
with open(os.path.join(data, "state.json"), "wb") as f:
    f.write(b'{"version":9,"sta')
top = max(vers)
srv = start(data, PORT)
try:
    s, h, b = req(PORT, "GET", "/api/state")
    rec = json.loads(b)
    ok(s == 200 and isinstance(rec.get("state"), dict) and rec["version"] == top + 2, "the newest good copy from history is used")
    ok(any(n.startswith("state.unreadable-") for n in os.listdir(data)), "the unreadable file is kept aside, not deleted")
    s, h, b = req(PORT, "PUT", "/api/state", json.dumps({"base": rec["version"], "state": {"bills": [], "after": 1}}), {"Content-Type": "application/json"})
    ok(s == 200, "saving works again afterwards")
finally:
    srv.terminate()
    srv.wait()

print("other names (BB_HOSTS)")
srv = start(data, PORT, BB_HOSTS="bills.example.com, .home.example.net")
try:
    ok(req(PORT, "GET", "/", headers={"Host": "bills.example.com"})[0] == 200, "a listed name is answered")
    ok(req(PORT, "GET", "/", headers={"Host": "nas.home.example.net:47219"})[0] == 200, "a listed ending is answered")
    ok(req(PORT, "GET", "/", headers={"Host": "other.example.com"})[0] == 403, "others are still refused")
finally:
    srv.terminate()
    srv.wait()

if os.geteuid() == 0:
    print("symlinks")
    outside = os.path.join(base, "outside.txt")
    open(outside, "w").write("x")
    os.chmod(outside, 0o644)
    os.symlink(outside, os.path.join(data, "link.txt"))
    srv = start(data, PORT)
    srv.terminate()
    srv.wait()
    st = os.stat(outside)
    ok(st.st_uid == 0 and (st.st_mode & 0o777) == 0o644, "a link in the data folder doesn't change the file it points at")

shutil.rmtree(base, ignore_errors=True)
print(("%d FAILED" % fails) if fails else "all server checks passed")
sys.exit(1 if fails else 0)
