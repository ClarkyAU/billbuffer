#!/usr/bin/env python3
"""Bill Buffer server: serves the app and keeps one shared copy of the household's data.

Passcode is optional. With none set, any device that can reach the server can use it (fine on a
trusted home network). A passcode can be turned on, changed or turned off from the app's Settings,
or set with BB_PASSCODE (8+ characters), which takes priority. With one set, devices must sign in.

Security:
- With a passcode, every data request needs a device token. A device gets one by signing in with the
  household passcode. Only a SHA-256 hash of each token is stored. A passcode set in the app is stored
  as a salted PBKDF2 hash, never as plain text. Changing or turning it off needs the current passcode.
- Wrong passcodes are rate limited per address, with a lockout.
- Saves are versioned. A save based on an old version is refused (409) instead of
  silently overwriting someone else's change. The last 30 versions are kept on disk.
- Root is dropped after preparing /data. Responses carry strict security headers.
Uses only the Python standard library.
"""
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, "site")
DATA = os.environ.get("BB_DATA", "/data")
PORT = int(os.environ.get("BB_PORT", "8080"))
PASSCODE = os.environ.get("BB_PASSCODE", "")
PLACEHOLDER = "change-me-to-something-long"
MIN_PASSCODE = 8
MAX_BODY = 5 * 1024 * 1024
TOKEN_DAYS = 180
HISTORY_KEEP = 30
FAIL_LIMIT, FAIL_WINDOW, LOCKOUT = 5, 600, 900

STATE_FILE = os.path.join(DATA, "state.json")
TOKENS_FILE = os.path.join(DATA, "tokens.json")
PASS_FILE = os.path.join(DATA, "passcode.json")
PBKDF2_ITER = 200_000
MAX_PASSCODE = 200
HISTORY_DIR = os.path.join(DATA, "history")

lock = threading.Lock()
fails = {}  # ip -> [timestamps]
locked_until = {}  # ip -> time
app_pass = None  # passcode set in the app: {"salt", "iter", "hash", "set"}

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")


def env_pass():
    """A passcode set in TrueNAS (BB_PASSCODE). It takes priority over one set in the app."""
    return PASSCODE not in ("", PLACEHOLDER)


def open_mode():
    return not env_pass() and app_pass is None


def passcode_ready():
    return not env_pass() or len(PASSCODE) >= MIN_PASSCODE


def lock_source():
    return "server" if env_pass() else "app" if app_pass else None


def hash_pass(passcode, salt, iterations):
    return hashlib.pbkdf2_hmac("sha256", passcode.encode("utf-8"), bytes.fromhex(salt), iterations).hex()


def passcode_matches(given):
    if env_pass():
        return hmac.compare_digest(given.encode("utf-8"), PASSCODE.encode("utf-8"))
    if app_pass:
        return hmac.compare_digest(hash_pass(given, app_pass["salt"], app_pass["iter"]), app_pass["hash"])
    return False


def load_app_pass():
    rec = read_json(PASS_FILE, None)
    if isinstance(rec, dict) and all(isinstance(rec.get(k), str) for k in ("salt", "hash")) and isinstance(rec.get("iter"), int):
        return rec
    return None


def now():
    return int(time.time())


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_tokens():
    toks = read_json(TOKENS_FILE, {})
    cutoff = now() - TOKEN_DAYS * 86400
    return {h: t for h, t in toks.items() if t.get("lastSeen", 0) >= cutoff}


def prepare_data_dir():
    os.makedirs(HISTORY_DIR, exist_ok=True)
    if os.geteuid() == 0:
        uid = gid = 65534  # nobody
        for base, dirs, files in os.walk(DATA):
            os.chown(base, uid, gid)
            os.chmod(base, 0o700)
            for name in files:
                p = os.path.join(base, name)
                os.chown(p, uid, gid)
                os.chmod(p, 0o600)
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
    os.umask(0o077)


class Handler(BaseHTTPRequestHandler):
    server_version = "BillBuffer"
    sys_version = ""

    # ---------- helpers ----------
    def client_ip(self):
        return self.client_address[0]

    def security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; manifest-src 'self'; "
            "worker-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        )

    def send_json(self, code, obj):
        body = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.security_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("too_large")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def same_origin(self):
        # Writes must come from the app's own page, not another site in the browser.
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host", "")
        return urlparse(origin).netloc == host

    def device_name(self):
        return "".join(c for c in (self.headers.get("X-BB-Device") or "")[:40] if c.isprintable()).strip()

    def auth(self):
        if open_mode():
            return "open", {"device": self.device_name() or "A device"}
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        h = token_hash(header[7:].strip())
        with lock:
            toks = load_tokens()
            for stored, info in toks.items():
                if hmac.compare_digest(stored, h):
                    if now() - info.get("lastSeen", 0) > 3600:
                        info["lastSeen"] = now()
                        write_json(TOKENS_FILE, toks)
                    return stored, info
        return None

    def log_message(self, fmt, *args):
        # Keep logs free of tokens and data: method, path and status only.
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    # ---------- routing ----------
    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            return self.api_get(path)
        return self.static(path)

    def do_HEAD(self):
        return self.do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if not self.same_origin():
            return self.send_json(403, {"error": "forbidden"})
        try:
            body = self.read_body()
        except ValueError:
            return self.send_json(413, {"error": "too_large"})
        except Exception:
            return self.send_json(400, {"error": "bad_json"})
        if path == "/api/login":
            return self.login(body)
        if path == "/api/passcode":
            return self.set_passcode(body)
        who = self.auth()
        if not who:
            return self.send_json(401, {"error": "signed_out"})
        if open_mode() and path in ("/api/logout", "/api/logout-all"):
            return self.send_json(200, {"ok": True})
        if path == "/api/logout":
            with lock:
                toks = load_tokens()
                toks.pop(who[0], None)
                write_json(TOKENS_FILE, toks)
            return self.send_json(200, {"ok": True})
        if path == "/api/logout-all":
            with lock:
                write_json(TOKENS_FILE, {})
            return self.send_json(200, {"ok": True})
        return self.send_json(404, {"error": "not_found"})

    def do_PUT(self):
        path = urlparse(self.path).path
        if path != "/api/state":
            return self.send_json(404, {"error": "not_found"})
        if not self.same_origin():
            return self.send_json(403, {"error": "forbidden"})
        who = self.auth()
        if not who:
            return self.send_json(401, {"error": "signed_out"})
        try:
            body = self.read_body()
        except ValueError:
            return self.send_json(413, {"error": "too_large"})
        except Exception:
            return self.send_json(400, {"error": "bad_json"})
        state = body.get("state")
        base = body.get("base")
        if not isinstance(state, dict) or not isinstance(state.get("bills"), list):
            return self.send_json(400, {"error": "bad_state"})
        with lock:
            cur = read_json(STATE_FILE, {"version": 0, "state": None})
            if base != cur.get("version", 0):
                return self.send_json(409, cur)
            if cur.get("state") is not None:
                stamp = time.strftime("%Y%m%d-%H%M%S")
                write_json(os.path.join(HISTORY_DIR, "state-%s-v%d.json" % (stamp, cur["version"])), cur)
                old = sorted(os.listdir(HISTORY_DIR))
                for name in old[:-HISTORY_KEEP]:
                    try:
                        os.remove(os.path.join(HISTORY_DIR, name))
                    except OSError:
                        pass
            new = {"version": cur.get("version", 0) + 1, "state": state, "updatedAt": now(), "updatedBy": who[1].get("device", "")}
            write_json(STATE_FILE, new)
        return self.send_json(200, {"version": new["version"], "updatedAt": new["updatedAt"]})

    # ---------- api ----------
    def api_get(self, path):
        if path == "/api/status":
            return self.send_json(200, {"app": "bill-buffer", "sync": True, "ready": passcode_ready(), "open": open_mode(), "lock": lock_source()})
        who = self.auth()
        if not who:
            return self.send_json(401, {"error": "signed_out"})
        if path == "/api/state":
            q = parse_qs(urlparse(self.path).query)
            with lock:
                cur = read_json(STATE_FILE, {"version": 0, "state": None})
            since = q.get("since", [None])[0]
            if since is not None and since.isdigit() and int(since) == cur.get("version", 0):
                return self.send_json(200, {"version": cur.get("version", 0), "unchanged": True})
            return self.send_json(200, cur)
        if path == "/api/devices":
            if open_mode():
                return self.send_json(200, {"devices": []})
            with lock:
                toks = load_tokens()
            devs = [{"device": t.get("device", ""), "created": t.get("created"), "lastSeen": t.get("lastSeen"), "you": h == who[0]} for h, t in toks.items()]
            devs.sort(key=lambda d: -(d["lastSeen"] or 0))
            return self.send_json(200, {"devices": devs})
        return self.send_json(404, {"error": "not_found"})

    # ---------- passcode ----------
    def locked_out(self, ip, t):
        """Returns a 429 response while this address is locked out, else None."""
        with lock:
            # forget old failures and finished lockouts so these never grow without limit
            for k in [k for k, v in fails.items() if not v or v[-1] <= t - FAIL_WINDOW]:
                fails.pop(k, None)
            for k in [k for k, v in locked_until.items() if v <= t]:
                locked_until.pop(k, None)
            if locked_until.get(ip, 0) > t:
                return self.send_json(429, {"error": "locked", "retryAfter": locked_until[ip] - t})
        return None

    def wrong_passcode(self, ip, t):
        time.sleep(1)
        with lock:
            recent = [x for x in fails.get(ip, []) if x > t - FAIL_WINDOW] + [t]
            fails[ip] = recent
            if len(recent) >= FAIL_LIMIT:
                locked_until[ip] = t + LOCKOUT
                fails[ip] = []
                return self.send_json(429, {"error": "locked", "retryAfter": LOCKOUT})
        return self.send_json(401, {"error": "wrong_passcode", "triesLeft": FAIL_LIMIT - len(recent)})

    def issue_token(self, ip, device, t, keep_others=True):
        token = secrets.token_urlsafe(32)
        with lock:
            fails.pop(ip, None)
            toks = load_tokens() if keep_others else {}
            toks[token_hash(token)] = {"device": device, "created": t, "lastSeen": t}
            write_json(TOKENS_FILE, toks)
        return token

    def login(self, body):
        ip, t = self.client_ip(), now()
        out = self.locked_out(ip, t)
        if out:
            return out
        if open_mode():
            return self.send_json(400, {"error": "no_passcode_needed"})
        if not passcode_ready():
            return self.send_json(503, {"error": "no_passcode"})
        given = str(body.get("passcode", ""))[:MAX_PASSCODE]
        device = str(body.get("device", "")).strip()[:40] or "Device"
        if not passcode_matches(given):
            return self.wrong_passcode(ip, t)
        return self.send_json(200, {"token": self.issue_token(ip, device, t)})

    def set_passcode(self, body):
        """Turn the passcode on, change it, or turn it off. Changing or turning it off needs a signed-in
        device and the current passcode. Every other device is signed out either way."""
        global app_pass
        ip, t = self.client_ip(), now()
        if env_pass():
            return self.send_json(409, {"error": "set_on_server"})
        new = str(body.get("new", ""))
        current = str(body.get("current", ""))[:MAX_PASSCODE]
        if new and not (MIN_PASSCODE <= len(new) <= MAX_PASSCODE):
            return self.send_json(400, {"error": "bad_length", "min": MIN_PASSCODE})
        if app_pass is not None:
            if not self.auth():
                return self.send_json(401, {"error": "signed_out"})
            out = self.locked_out(ip, t)
            if out:
                return out
            if not passcode_matches(current):
                return self.wrong_passcode(ip, t)
        elif not new:
            return self.send_json(400, {"error": "already_off"})
        with lock:
            if new:
                salt = secrets.token_hex(16)
                rec = {"salt": salt, "iter": PBKDF2_ITER, "hash": hash_pass(new, salt, PBKDF2_ITER), "set": t}
                write_json(PASS_FILE, rec)
                app_pass = rec
            else:
                try:
                    os.remove(PASS_FILE)
                except FileNotFoundError:
                    pass
                app_pass = None
            write_json(TOKENS_FILE, {})
        if new:
            return self.send_json(200, {"on": True, "token": self.issue_token(ip, self.device_name() or "Device", t, keep_others=False)})
        return self.send_json(200, {"on": False})

    # ---------- static files ----------
    def static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        full = os.path.realpath(os.path.join(SITE, path.lstrip("/")))
        if not full.startswith(os.path.realpath(SITE) + os.sep) or not os.path.isfile(full):
            # a missing file such as a font or icon is a real 404; any other path opens the app
            if os.path.splitext(path)[1]:
                return self.send_json(404, {"error": "not_found"})
            full = os.path.join(SITE, "index.html")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") or ctype.endswith("json") else ""))
        self.send_header("Content-Length", str(len(data)))
        name = os.path.basename(full)
        self.send_header("Cache-Control", "no-cache" if name in ("index.html", "sw.js", "manifest.webmanifest") else "public, max-age=86400")
        self.security_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)


def main():
    global app_pass
    prepare_data_dir()
    app_pass = load_app_pass()
    if env_pass() and app_pass:
        print("BB_PASSCODE is set, so it is used instead of the passcode set in the app.", flush=True)
    if open_mode():
        print("No passcode set: any device that can reach this server can view and change the bills.", flush=True)
    elif not passcode_ready():
        print("WARNING: BB_PASSCODE must be at least %d characters. Sign-in is disabled until then." % MIN_PASSCODE, flush=True)
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    httpd.daemon_threads = True
    print("Bill Buffer is running on port %d" % PORT, flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
