#!/usr/bin/env python3
"""Bill Buffer server: serves the app and keeps one shared copy of the household's data.

Passcode is optional and off by default. With none set, any device that can reach the server can use
it (fine on a trusted home network). A passcode can be turned on, changed or turned off from the app's
Settings, or set with BB_PASSCODE (8+ characters), which takes priority. With one set, devices must sign in.

Security:
- Only requests addressed to this server by an IP address, a local name (e.g. truenas, nas.local,
  *.ts.net) or a name listed in BB_HOSTS are answered. This stops other websites reaching it through
  DNS rebinding, which matters most when no passcode is set.
- With a passcode, every data request needs a device token. A device gets one by signing in with the
  household passcode. Only a SHA-256 hash of each token is stored. A passcode set in the app is stored
  as a salted PBKDF2 hash, never as plain text. Changing or turning it off needs the current passcode.
- Wrong passcodes are rate limited per address, with a lockout.
- Saves are versioned. A save based on an old version is refused (409) instead of silently
  overwriting someone else's change. Earlier versions are kept on disk: every one from the last
  few saves, one an hour for two days, and one a day for 30 days.
- If state.json can't be read at start-up, it is set aside and the newest good copy from history is used.
- Root is dropped after preparing /data. Responses carry strict security headers, and the page's
  script is allowed by its hash only.
Uses only the Python standard library.
"""
import base64
import gzip
import hashlib
import hmac
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, "site")
DATA = os.environ.get("BB_DATA", "/data")
PORT = int(os.environ.get("BB_PORT", "8080"))
PASSCODE = os.environ.get("BB_PASSCODE", "")
PLACEHOLDER = "change-me-to-something-long"
MIN_PASSCODE = 8
MAX_PASSCODE = 200
MAX_BODY = 5 * 1024 * 1024
MAX_SMALL_BODY = 4096  # sign-in and passcode requests
TOKEN_DAYS = 180
FAIL_LIMIT, FAIL_WINDOW, LOCKOUT = 5, 600, 900
PBKDF2_ITER = 200_000
REQUEST_TIMEOUT = int(os.environ.get("BB_TIMEOUT", "30"))  # seconds a quiet connection is kept
HISTORY_RECENT, HISTORY_HOURS, HISTORY_DAYS = 10, 48, 30

# Names this server answers to, besides IP addresses and local names. Comma separated.
# A name starting with a dot allows every name ending with it. "*" turns the check off.
EXTRA_HOSTS = {h.strip().lower() for h in os.environ.get("BB_HOSTS", "").split(",") if h.strip()}
LOCAL_SUFFIXES = (".local", ".lan", ".home", ".internal", ".home.arpa", ".localdomain", ".localhost", ".ts.net")

STATE_FILE = os.path.join(DATA, "state.json")
TOKENS_FILE = os.path.join(DATA, "tokens.json")
PASS_FILE = os.path.join(DATA, "passcode.json")
HISTORY_DIR = os.path.join(DATA, "history")

lock = threading.Lock()
fails = {}  # ip -> [timestamps]
locked_until = {}  # ip -> time
app_pass = None  # passcode set in the app: {"salt", "iter", "hash", "set"}
state = {"version": 0, "state": None}  # the shared copy, kept in memory; state.json mirrors it
state_body = b""  # state encoded once per save, for fast reads
tokens = {}  # token hash -> {"device", "created", "lastSeen"}
files = {}  # url path -> static file, read once at start-up
csp = ""

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")


class BadRequest(Exception):
    def __init__(self, code, error):
        super().__init__(error)
        self.code, self.error = code, error


# ---------- passcode ----------
def env_pass():
    """A passcode set in the container (BB_PASSCODE). It takes priority over one set in the app."""
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


# ---------- files ----------
def now():
    return int(time.time())


def read_json(path, default):
    """Missing or unreadable files give the default."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
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


def live_tokens():
    """Drops tokens not used for TOKEN_DAYS. Call with the lock held."""
    cutoff = now() - TOKEN_DAYS * 86400
    for h in [h for h, t in tokens.items() if t.get("lastSeen", 0) < cutoff]:
        tokens.pop(h, None)
    return tokens


def save_tokens():
    write_json(TOKENS_FILE, tokens)


def set_state(new):
    global state, state_body
    state = new
    state_body = json.dumps(new, separators=(",", ":")).encode("utf-8")


# ---------- history ----------
HISTORY_NAME = re.compile(r"^state-(\d{8})-(\d{2})(\d{4})-v(\d+)\.json$")


def history_names():
    try:
        return sorted(n for n in os.listdir(HISTORY_DIR) if HISTORY_NAME.match(n))
    except OSError:
        return []


def prune_history():
    """Keeps the last few saves, the newest save of each hour for two days and of each day for 30 days."""
    names = history_names()
    keep, seen, t = set(names[-HISTORY_RECENT:]), set(), time.time()
    for n in reversed(names):
        day, hour = HISTORY_NAME.match(n).group(1, 2)
        try:
            age = t - time.mktime(time.strptime(day + hour, "%Y%m%d%H"))
        except ValueError:
            keep.add(n)
            continue
        key = day + hour if age < HISTORY_HOURS * 3600 else day if age < HISTORY_DAYS * 86400 else None
        if key and key not in seen:
            seen.add(key)
            keep.add(n)
    for n in names:
        if n not in keep:
            try:
                os.remove(os.path.join(HISTORY_DIR, n))
            except OSError:
                pass


def load_state():
    """Reads state.json. If it exists but can't be read, it is set aside and the newest good history copy is used."""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            cur = json.load(f)
        if isinstance(cur, dict) and isinstance(cur.get("version"), int):
            return cur
    except FileNotFoundError:
        return {"version": 0, "state": None}
    except (OSError, ValueError):
        pass
    aside = os.path.join(DATA, "state.unreadable-%s.json" % time.strftime("%Y%m%d-%H%M%S"))
    try:
        os.replace(STATE_FILE, aside)
    except OSError:
        pass
    names = history_names()
    top = max((int(HISTORY_NAME.match(n).group(4)) for n in names), default=0)
    good = None
    for n in reversed(names):
        rec = read_json(os.path.join(HISTORY_DIR, n), None)
        if isinstance(rec, dict) and isinstance(rec.get("state"), dict):
            good = rec
            break
    # A fresh version number, so every device notices and loads the recovered copy.
    rec = {"version": top + 2, "state": good["state"] if good else None, "updatedAt": now(), "updatedBy": "Recovered"}
    write_json(STATE_FILE, rec)
    print("state.json could not be read, so it was moved to %s and %s." % (
        os.path.basename(aside), "the newest good copy from history is in use" if good else "no good copy was found"), flush=True)
    return rec


# ---------- start-up ----------
def prepare_data_dir():
    os.makedirs(HISTORY_DIR, exist_ok=True)
    if os.geteuid() == 0:
        uid = gid = 65534  # nobody
        for base, dirs, names in os.walk(DATA):
            os.chown(base, uid, gid, follow_symlinks=False)
            os.chmod(base, 0o700)
            for name in names:
                p = os.path.join(base, name)
                if os.path.islink(p):
                    continue  # never change ownership of whatever a link points at
                os.chown(p, uid, gid)
                os.chmod(p, 0o600)
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
    os.umask(0o077)


COMPRESS = (".html", ".js", ".json", ".webmanifest", ".css", ".svg", ".txt")


def load_site():
    """Reads the app's files once. Text files are also kept gzipped."""
    global csp
    for base, dirs, names in os.walk(SITE):
        for name in names:
            full = os.path.join(base, name)
            if os.path.islink(full) or name.startswith("."):
                continue
            with open(full, "rb") as f:
                data = f.read()
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("json"):
                ctype += "; charset=utf-8"
            tag = hashlib.sha256(data).hexdigest()[:20]
            gz = gzip.compress(data, 9, mtime=0) if name.endswith(COMPRESS) else None
            files["/" + os.path.relpath(full, SITE).replace(os.sep, "/")] = {
                "data": data, "gz": gz if gz and len(gz) < len(data) else None, "type": ctype, "etag": '"%s"' % tag,
                "cache": "no-cache" if name in ("index.html", "sw.js", "manifest.webmanifest") else "public, max-age=86400"}
    page = files.get("/index.html", {}).get("data", b"").decode("utf-8", "replace")
    hashes = " ".join("'sha256-%s'" % base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode()
                      for s in re.findall(r"<script>(.*?)</script>", page, re.S))
    csp = ("default-src 'self'; script-src 'self' %s; style-src 'self' 'unsafe-inline'; "
           "img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; manifest-src 'self'; "
           "worker-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'" % hashes).replace("  ", " ")


def host_allowed(header):
    """True for an IP address, a local name, or a name in BB_HOSTS."""
    if "*" in EXTRA_HOSTS:
        return True
    host = (header or "").strip().lower().rstrip(".")
    if not host:
        return True  # only non-browser clients leave Host out
    if host.startswith("["):
        name = host[1:host.find("]")] if "]" in host else host[1:]
    else:
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    name = name.rstrip(".")
    if host in EXTRA_HOSTS or name in EXTRA_HOSTS or any(s.startswith(".") and name.endswith(s) for s in EXTRA_HOSTS):
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    return "." not in name or name.endswith(LOCAL_SUFFIXES)


class Handler(BaseHTTPRequestHandler):
    server_version = "BillBuffer"
    sys_version = ""
    timeout = REQUEST_TIMEOUT  # a connection that goes quiet is closed instead of held open

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
        self.send_header("Content-Security-Policy", csp)

    def send_body(self, code, body, ctype, cache="no-store", extra=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        for k, v in extra:
            self.send_header(k, v)
        self.security_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, code, obj):
        self.send_body(code, json.dumps(obj, separators=(",", ":")).encode("utf-8"), "application/json; charset=utf-8")

    def read_body(self, limit=MAX_BODY):
        raw_len = self.headers.get("Content-Length") or "0"
        if not raw_len.strip().isdigit():
            raise BadRequest(400, "bad_request")
        length = int(raw_len)
        if length == 0:
            return {}
        if length > limit:
            raise BadRequest(413, "too_large")
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise BadRequest(400, "bad_json")
        if not isinstance(body, dict):
            raise BadRequest(400, "bad_json")
        return body

    def same_origin(self):
        # Writes must come from the app's own page, not another site in the browser.
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return urlparse(origin).netloc == self.headers.get("Host", "")

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
            info = live_tokens().get(h)
            if info is None:
                return None
            if now() - info.get("lastSeen", 0) > 3600:
                info["lastSeen"] = now()
                save_tokens()
            return h, dict(info)

    def log_message(self, fmt, *args):
        # Keep logs free of tokens and data: method, path and status only. Health checks are skipped.
        if (self.path or "").startswith("/api/status"):
            return
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    def run(self, fn):
        """Every request goes through here: wrong addresses are refused, and errors give a clean reply."""
        try:
            if not host_allowed(self.headers.get("Host")):
                return self.refuse_host()
            return fn(urlparse(self.path).path)
        except BadRequest as e:
            return self.send_json(e.code, {"error": e.error})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception as e:
            sys.stderr.write("error handling %s %s: %s\n" % (self.command, urlparse(self.path).path, type(e).__name__))
            try:
                self.send_json(500, {"error": "server_error"})
            except Exception:
                self.close_connection = True

    def refuse_host(self):
        name = "".join(c for c in (self.headers.get("Host") or "")[:100] if c.isalnum() or c in ".-:[]")
        if urlparse(self.path).path.startswith("/api/"):
            return self.send_json(403, {"error": "unknown_address"})
        page = ("<!doctype html><meta charset=utf-8><title>Bill Buffer</title><body style=\"font:16px system-ui;padding:24px;max-width:36em\">"
                "<h1>Address not allowed</h1><p>Bill Buffer only answers to its IP address and local names. "
                "To use <b>%s</b>, add it to <code>BB_HOSTS</code> in your compose file and restart the app.</p>" % name)
        return self.send_body(403, page.encode("utf-8"), "text/html; charset=utf-8")

    # ---------- routing ----------
    def do_GET(self):
        self.run(lambda p: self.api_get(p) if p.startswith("/api/") else self.static(p))

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        self.run(self.post)

    def do_PUT(self):
        self.run(self.put)

    def post(self, path):
        if not self.same_origin():
            return self.send_json(403, {"error": "forbidden"})
        if path == "/api/login":
            return self.login(self.read_body(MAX_SMALL_BODY))
        if path == "/api/passcode":
            return self.set_passcode(self.read_body(MAX_SMALL_BODY))
        who = self.auth()
        if not who:
            return self.send_json(401, {"error": "signed_out"})
        self.read_body(MAX_SMALL_BODY)
        if open_mode() and path in ("/api/logout", "/api/logout-all"):
            return self.send_json(200, {"ok": True})
        if path == "/api/logout":
            with lock:
                tokens.pop(who[0], None)
                save_tokens()
            return self.send_json(200, {"ok": True})
        if path == "/api/logout-all":
            with lock:
                tokens.clear()
                save_tokens()
            return self.send_json(200, {"ok": True})
        return self.send_json(404, {"error": "not_found"})

    def put(self, path):
        if path != "/api/state":
            return self.send_json(404, {"error": "not_found"})
        if not self.same_origin():
            return self.send_json(403, {"error": "forbidden"})
        who = self.auth()
        if not who:
            return self.send_json(401, {"error": "signed_out"})
        body = self.read_body()
        new_state, base = body.get("state"), body.get("base")
        if not isinstance(new_state, dict) or not isinstance(new_state.get("bills"), list):
            return self.send_json(400, {"error": "bad_state"})
        with lock:
            cur = state
            if base != cur.get("version", 0):
                return self.send_body(409, state_body, "application/json; charset=utf-8")
            if cur.get("state") is not None:
                stamp = time.strftime("%Y%m%d-%H%M%S")
                write_json(os.path.join(HISTORY_DIR, "state-%s-v%d.json" % (stamp, cur["version"])), cur)
                prune_history()
            new = {"version": cur.get("version", 0) + 1, "state": new_state, "updatedAt": now(), "updatedBy": who[1].get("device", "")}
            write_json(STATE_FILE, new)
            set_state(new)
        return self.send_json(200, {"version": new["version"], "updatedAt": new["updatedAt"]})

    # ---------- api ----------
    def api_get(self, path):
        if path == "/api/status":
            return self.send_json(200, {"app": "bill-buffer", "sync": True, "ready": passcode_ready(), "open": open_mode(), "lock": lock_source()})
        who = self.auth()
        if not who:
            return self.send_json(401, {"error": "signed_out"})
        if path == "/api/state":
            since = parse_qs(urlparse(self.path).query).get("since", [None])[0]
            with lock:
                version, body = state.get("version", 0), state_body
            if since is not None and since.isdigit() and int(since) == version:
                return self.send_json(200, {"version": version, "unchanged": True})
            return self.send_body(200, body, "application/json; charset=utf-8")
        if path == "/api/devices":
            if open_mode():
                return self.send_json(200, {"devices": []})
            with lock:
                devs = [{"device": t.get("device", ""), "created": t.get("created"), "lastSeen": t.get("lastSeen"), "you": h == who[0]}
                        for h, t in live_tokens().items()]
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
            if not keep_others:
                tokens.clear()
            live_tokens()[token_hash(token)] = {"device": device, "created": t, "lastSeen": t}
            save_tokens()
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
        device = "".join(c for c in str(body.get("device", ""))[:40] if c.isprintable()).strip() or "Device"
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
            tokens.clear()
            save_tokens()
        if new:
            return self.send_json(200, {"on": True, "token": self.issue_token(ip, self.device_name() or "Device", t, keep_others=False)})
        return self.send_json(200, {"on": False})

    # ---------- static files ----------
    def static(self, path):
        f = files.get("/index.html" if path in ("", "/") else path)
        if f is None:
            # a missing file such as a font or icon is a real 404; any other path opens the app
            if os.path.splitext(path)[1]:
                return self.send_json(404, {"error": "not_found"})
            f = files.get("/index.html")
            if f is None:
                return self.send_json(404, {"error": "not_found"})
        zipped = f["gz"] is not None and "gzip" in (self.headers.get("Accept-Encoding") or "").lower()
        etag = f["etag"][:-1] + '-gz"' if zipped else f["etag"]
        extra = [("ETag", etag)] + ([("Vary", "Accept-Encoding")] if f["gz"] is not None else [])
        match = self.headers.get("If-None-Match") or ""
        if etag in [m.strip() for m in match.split(",")] or match.strip() == "*":
            self.send_response(304)
            for k, v in extra:
                self.send_header(k, v)
            self.send_header("Cache-Control", f["cache"])
            self.end_headers()
            return
        if zipped:
            extra.append(("Content-Encoding", "gzip"))
        return self.send_body(200, f["gz"] if zipped else f["data"], f["type"], f["cache"], extra)


def main():
    global app_pass, tokens
    prepare_data_dir()
    load_site()
    app_pass = load_app_pass()
    toks = read_json(TOKENS_FILE, {})
    tokens = {h: t for h, t in toks.items() if isinstance(t, dict)} if isinstance(toks, dict) else {}
    set_state(load_state())
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
