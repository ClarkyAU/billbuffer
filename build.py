#!/usr/bin/env python3
"""Builds the app from src/.

  site/                 what the server serves (committed, and baked into the Docker image)
  build/preview.html    a stand-alone copy that keeps data in the browser (Google Fonts, no server)
  build/local.html      the site's page without the server, for the click-through tests
  build/app.js          the site's script, for the figure and migration tests

Bump BUILD for every change you ship: it shows at the bottom of Settings and makes phones fetch the update.
"""
import os
import re
import shutil

BUILD = 34

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC, SITE, OUT = (os.path.join(ROOT, d) for d in ("src", "site", "build"))
src = open(os.path.join(SRC, "app.html"), encoding="utf-8").read()
os.makedirs(OUT, exist_ok=True)

# 1. Stand-alone preview
preview = src.replace("<!--HEAD-->", '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,100..900&family=Onest:wght@400..800&display=swap">').replace("/*SW*/", "")
open(os.path.join(OUT, "preview.html"), "w", encoding="utf-8").write(preview)

# 2. The served site
shutil.rmtree(SITE, ignore_errors=True)
os.makedirs(os.path.join(SITE, "fonts"))
for f in ("icon-192.png", "icon-512.png", "icon-maskable-512.png", "manifest.webmanifest"):
    shutil.copy(os.path.join(SRC, f), os.path.join(SITE, f))
FONTS = [("Archivo", "archivo.woff2", "100 900", "62% 125%"), ("Onest", "onest.woff2", "100 900", "100%")]
faces = ""
for fam, name, weight, stretch in FONTS:
    shutil.copy(os.path.join(SRC, "fonts", name), os.path.join(SITE, "fonts", name))
    faces += "@font-face{font-family:'%s';src:url(fonts/%s) format('woff2');font-weight:%s;font-stretch:%s;font-style:normal;font-display:swap}\n" % (fam, name, weight, stretch)
body = src.replace('<title>Bill Buffer</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n<!--HEAD-->\n', "")
body = body.replace("/*SERVER_MODE*/false", "true").replace("/*BUILD*/preview", "build %d" % BUILD)
body = body.replace("/*SW*/", "if('serviceWorker' in navigator&&(location.protocol==='https:'||location.hostname==='localhost'))navigator.serviceWorker.register('sw.js').catch(()=>{});")
style_end = body.index("</style>") + len("</style>")
head = ('<meta name="theme-color" content="#1E1D1B">\n<link rel="manifest" href="manifest.webmanifest">\n'
        '<link rel="icon" href="icon-192.png">\n<link rel="apple-touch-icon" href="icon-192.png">\n')
doc = ('<!doctype html>\n<html lang="en-AU">\n<head>\n<meta charset="utf-8">\n'
       '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n<title>Bill Buffer</title>\n'
       + head + body[:style_end].replace("<style>", "<style>\n" + faces, 1).replace(":root{\n  --bg", ":root{\n  color-scheme:light;\n  --bg", 1)
       + "\n</head>\n<body>\n" + body[style_end:].strip() + "\n</body>\n</html>\n")
open(os.path.join(SITE, "index.html"), "w", encoding="utf-8").write(doc)
sw = open(os.path.join(SRC, "sw.js"), encoding="utf-8").read().replace("bill-buffer-v1", "bill-buffer-v%d" % BUILD)
open(os.path.join(SITE, "sw.js"), "w", encoding="utf-8").write(sw)

# 3. Test copies
local = doc.replace("const SERVER_MODE=true;", "const SERVER_MODE=false;")
assert local != doc
open(os.path.join(OUT, "local.html"), "w", encoding="utf-8").write(local.replace("url(fonts/", "url(../site/fonts/"))
open(os.path.join(OUT, "app.js"), "w", encoding="utf-8").write(re.search(r"<script>(.*)</script>", doc, re.S).group(1))
print("built build %d" % BUILD)
