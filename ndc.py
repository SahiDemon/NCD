"""
Nexus Download Collection (NDC) - Python Script
================================================
Sends every mod in a NexusMods collection to Vortex using pre-keyed NXM
links so you never see the Premium dialog.

Run: double-click "Run NDC.bat"  OR  python ndc.py
"""

import json
import os
import re
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

PYTHON = sys.executable

# ── Auto-install missing deps ──────────────────────────────────────────────
def _ensure(pkg, import_name=None):
    import_name = import_name or pkg
    try:
        __import__(import_name)
    except ImportError:
        print(f"[NDC] Installing {pkg}...")
        subprocess.check_call([PYTHON, "-m", "pip", "install", pkg, "-q"])

_ensure("requests")
_ensure("browser-cookie3", "browser_cookie3")
_ensure("curl-cffi", "curl_cffi")

import requests
import browser_cookie3
from curl_cffi import requests as cffi_requests

# ── Paths ──────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
CONFIG_FILE  = SCRIPT_DIR / "ndc_config.json"
HISTORY_FILE = SCRIPT_DIR / "ndc_history.json"

GRAPHQL_URL     = "https://api-router.nexusmods.com/graphql"
GENERATE_DL_URL = "https://www.nexusmods.com/Core/Libs/Common/Managers/Downloads?GenerateDownloadUrl"

# ── ANSI colours ───────────────────────────────────────────────────────────
C = {
    "reset":  "\033[0m",
    "green":  "\033[92m",
    "red":    "\033[91m",
    "yellow": "\033[93m",
    "cyan":   "\033[96m",
    "bold":   "\033[1m",
    "dim":    "\033[2m",
}
def col(text, *keys):
    prefix = "".join(C.get(k, "") for k in keys)
    return f"{prefix}{text}{C['reset']}"

def convert_size(kb):
    mb = kb / 1024
    gb = mb / 1024
    return f"{gb:.2f} GB" if gb >= 1 else f"{mb:.2f} MB"

# ── JSON helpers ───────────────────────────────────────────────────────────
def load_json(path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return default

def save_json(path, data):
    path.write_text(json.dumps(data, indent=2), "utf-8")

# ── Config ─────────────────────────────────────────────────────────────────
def load_config():
    return load_json(CONFIG_FILE, {
        "api_key":             "",
        "cookie_string":       "",
        "mode":                "cookie",
        "open_in_vortex":      True,
        "pause_between":       5,
        "download_speed_mbps": 1.5,
    })

def save_config(cfg):
    save_json(CONFIG_FILE, cfg)

# ── URL parser ─────────────────────────────────────────────────────────────
def parse_url(url):
    parts = [p for p in urlparse(url.strip()).path.split("/") if p]
    if len(parts) >= 4 and parts[2] == "collections":
        rev = int(parts[5]) if len(parts) >= 6 and parts[4] == "revisions" else None
        return parts[1], parts[3], rev
    return None, None, None

# ── Cookie jar ─────────────────────────────────────────────────────────────
_cookie_jar = None

def _jar_from_string(cookie_str):
    jar = requests.cookies.RequestsCookieJar()
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            name, _, value = part.partition("=")
            jar.set(name.strip(), value.strip(), domain=".nexusmods.com", path="/")
    return jar

def get_cookie_jar(cfg):
    global _cookie_jar
    if _cookie_jar is not None:
        return _cookie_jar

    # Try auto browser extraction
    for name, loader in [("Chrome", browser_cookie3.chrome), ("Edge", browser_cookie3.edge), ("Firefox", browser_cookie3.firefox)]:
        try:
            jar = loader(domain_name=".nexusmods.com")
            if {c.name: c.value for c in jar}:
                print(col(f"  Loaded cookies from {name}", "green"))
                _cookie_jar = jar
                return jar
        except Exception:
            pass

    # Use saved cookie string
    if cfg.get("cookie_string"):
        print(col("  Using saved cookie string.", "green"))
        _cookie_jar = _jar_from_string(cfg["cookie_string"])
        return _cookie_jar

    # Prompt
    print(col("\n  Browser cookies not found. Paste your NexusMods Cookie header once.", "yellow"))
    print("  Steps: F12 -> Network -> refresh nexusmods.com -> click request -> Request Headers -> Cookie:")
    print()
    cookie_str = input("  Paste Cookie value: ").strip()
    if not cookie_str:
        return None
    cfg["cookie_string"] = cookie_str
    save_config(cfg)
    _cookie_jar = _jar_from_string(cookie_str)
    return _cookie_jar

# ── GraphQL mod list ───────────────────────────────────────────────────────
QUERY = """
query CollectionRevisionMods($revision:Int,$slug:String!,$viewAdultContent:Boolean){
  collectionRevision(revision:$revision,slug:$slug,viewAdultContent:$viewAdultContent){
    modFiles{
      fileId optional
      file{
        fileId name uri size version date
        mod{ adult modId name version game{ domainName id } }
      }
    }
  }
}
"""

def fetch_mods(slug, revision, api_key):
    print(col(f"\n  Fetching mod list for '{slug}'...", "cyan"))
    r = requests.post(
        GRAPHQL_URL,
        json={
            "query": QUERY,
            "variables": {"slug": slug, "viewAdultContent": True, "revision": revision},
            "operationName": "CollectionRevisionMods",
        },
        headers={"Content-Type": "application/json", "apikey": api_key},
        timeout=30,
    )
    r.raise_for_status()
    cr = r.json().get("data", {}).get("collectionRevision")
    if not cr:
        print(col("  [ERROR] No data — check the collection URL or API key.", "red"))
        return []

    mods = cr["modFiles"]
    for m in mods:
        d   = m["file"]["mod"]["game"]["domainName"]
        mid = m["file"]["mod"]["modId"]
        fid = m["file"]["fileId"]
        m["file"]["url"] = f"https://www.nexusmods.com/{d}/mods/{mid}?tab=files&file_id={fid}"
    return mods

# ── Download link ──────────────────────────────────────────────────────────
# Regex patterns from the original userscript (same order, same logic)
_NXM_PATTERNS = [
    r"const downloadUrl = '([^']+)'",
    r'id="slowDownloadButton"[^>]*data-download-url="([^"]+)"',
    r'data-download-url="([^"]+)"',
    r'download-url="([^"]+)"',
    r'"url"\s*:\s*"([^"]+)"',
]

def fetch_keyed_nxm(mod, jar):
    """
    3-step approach that mirrors the original userscript:
      1. Fetch the mod download page HTML with &nmm=1 and scrape for a
         pre-keyed NXM/CDN URL using the same regex patterns as the JS.
      2. Fall back to GenerateDownloadUrl API with nmm=1.
      3. Fall back to GenerateDownloadUrl API without nmm.

    A keyed NXM link (nxm://...?key=X&expires=Y) lets Vortex download
    directly without showing the Premium dialog.
    """
    fid     = mod["fileId"]
    game_id = mod["file"]["mod"]["game"]["id"]
    ref_url = mod["file"]["url"]

    # Ads-bypass cookie (same as bypassNexusAdsCookie() in the userscript)
    jar.set("ab", f"0|{int(time.time()) + 300}", domain=".nexusmods.com", path="/")
    cookies = {c.name: c.value for c in jar}

    page_h = {
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         "https://www.nexusmods.com/",
        "Sec-Fetch-Site":  "same-origin",
        "Sec-Fetch-Mode":  "navigate",
        "Sec-Fetch-Dest":  "document",
    }
    api_h = {
        "Content-Type":     "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer":          ref_url,
        "X-Requested-With": "XMLHttpRequest",
        "Accept":           "application/json, text/javascript, */*; q=0.01",
        "Accept-Language":  "en-US,en;q=0.9",
        "Origin":           "https://www.nexusmods.com",
        "Sec-Fetch-Site":   "same-origin",
        "Sec-Fetch-Mode":   "cors",
        "Sec-Fetch-Dest":   "empty",
    }

    # ── Step 1: HTML scrape (same as Step 1 in the userscript) ────────────
    try:
        r = cffi_requests.get(
            f"{ref_url}&nmm=1",
            headers=page_h,
            cookies=cookies,
            impersonate="chrome136",
            timeout=25,
            allow_redirects=True,
        )
        if r.ok:
            text = r.text
            for pattern in _NXM_PATTERNS:
                m = re.search(pattern, text, re.DOTALL)
                if m:
                    url = m.group(1).replace("&amp;", "&")
                    # Accept NXM links with key/expires, or CDN URLs
                    if url and ("nxm://" in url or "nexus-cdn.com" in url):
                        # Only use NXM links that carry a key (keyless = dialog)
                        if "nxm://" in url and "key=" not in url:
                            break  # fall through to API
                        return url
    except Exception as e:
        print(col(f"    [WARN] HTML scrape: {e}", "yellow"))

    # ── Step 2 & 3: GenerateDownloadUrl API ───────────────────────────────
    for nmm in (True, False):
        body = f"fid={fid}&game_id={game_id}" + ("&nmm=1" if nmm else "")
        try:
            r = cffi_requests.post(
                GENERATE_DL_URL,
                data=body,
                headers=api_h,
                cookies=cookies,
                impersonate="chrome136",
                timeout=20,
            )
            if r.ok:
                try:
                    data = r.json()
                    url  = (data.get("url") or data.get("URI") or
                            data.get("src")  or data.get("download_url") or "")
                    if url:
                        return url.replace("&amp;", "&")
                except Exception:
                    pass
            elif r.status_code == 403:
                print(col("    [WARN] Session expired — go to Settings and re-paste cookies", "yellow"))
                break
        except Exception as e:
            print(col(f"    [WARN] API: {e}", "yellow"))

    return ""

# ── REST API Download Link (API Mode) ──────────────────────────────────────
NEXUS_API = "https://api.nexusmods.com/v1"

def fetch_download_link(mod, api_key):
    """
    Get a download link via the NexusMods REST API.
    Returns an nxm:// link (for Vortex) or a CDN URL.
    """
    file_id = mod["fileId"]
    mod_id  = mod["file"]["mod"]["modId"]
    domain  = mod["file"]["mod"]["game"]["domainName"]

    url = f"{NEXUS_API}/games/{domain}/mods/{mod_id}/files/{file_id}/download_link.json"
    headers = {"apikey": api_key, "Accept": "application/json"}

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.ok:
            links = resp.json()
            if links and isinstance(links, list):
                for lnk in links:
                    if "URI" in lnk:
                        return lnk["URI"]
    except Exception as e:
        print(col(f"    [WARN] REST API error: {e}", "yellow"))

    # Fallback to standard keyless NXM link
    return f"nxm://{domain}/mods/{mod_id}/files/{file_id}"

# ── History ────────────────────────────────────────────────────────────────
def load_history(game, slug, kind):
    h = load_json(HISTORY_FILE, {})
    return set(h.get(game, {}).get(slug, {}).get(kind, []))

def save_history(game, slug, kind, done):
    h = load_json(HISTORY_FILE, {})
    h.setdefault(game, {}).setdefault(slug, {})[kind] = list(done)
    save_json(HISTORY_FILE, h)

def clear_history(game, slug, kind):
    h = load_json(HISTORY_FILE, {})
    if game in h and slug in h[game] and kind in h[game][slug]:
        h[game][slug][kind] = []
        save_json(HISTORY_FILE, h)

# ── Download engine ────────────────────────────────────────────────────────
def download_mods(mods, game, slug, kind, cfg):
    total       = len(mods)
    speed_mbps  = cfg["download_speed_mbps"]
    pause_extra = cfg["pause_between"]

    if not total:
        print(col("  No mods to download.", "yellow"))
        return

    mode = cfg.get("mode", "cookie")
    jar = None
    if mode == "cookie":
        jar = get_cookie_jar(cfg)
        if jar is None:
            return

    done = load_history(game, slug, kind)
    if done:
        ans = input(col(f"\n  {len(done)}/{total} already done. Skip them? [Y/n]: ", "yellow")).strip().lower()
        if ans == "n":
            done = set()
            clear_history(game, slug, kind)

    failed = []
    pad_w  = len(str(total))

    print(col(f"\n  Starting {total} mods...\n", "bold"))
    print(col("─" * 60, "dim"))

    for idx, mod in enumerate(mods, 1):
        label = f"[{str(idx).zfill(pad_w)}/{total}]"
        name  = mod["file"]["name"]
        size  = mod["file"]["size"]
        fid   = mod["fileId"]
        req   = col("Optional", "dim") if mod["optional"] else col("Mandatory", "cyan")

        if fid in done:
            print(col(f"  {label} SKIP  {name}", "dim"))
            continue

        print(f"  {label} {col(name, 'bold')}  {col(convert_size(size), 'dim')}  {req}")

        if mode == "cookie":
            url = fetch_keyed_nxm(mod, jar)
        else:
            url = fetch_download_link(mod, cfg["api_key"])

        if not url:
            print(col("    FAILED - could not get download link", "red"))
            print(col(f"      Manual: {mod['file']['url']}", "dim"))
            failed.append(mod)
        else:
            if mode == "cookie" or cfg.get("open_in_vortex", True):
                webbrowser.open(url)
                short = url[:80] + "..." if len(url) > 80 else url
                print(col(f"    -> {short}", "green"))
            else:
                print(col(f"    -> Link: {url}", "green"))
            done.add(fid)
            save_history(game, slug, kind, done)

        if idx < total:
            smart = (round(size / 1024 / speed_mbps) + pause_extra) if pause_extra > 0 else 0
            if smart > 0:
                print(col(f"    Waiting {smart}s...", "dim"), end="", flush=True)
                try:
                    time.sleep(smart)
                except KeyboardInterrupt:
                    print(col(" skipped.", "yellow"))
                    continue
                print()

    print(col("─" * 60, "dim"))

    if failed:
        print(col(f"\n  {len(failed)} mod(s) failed:", "red"))
        for m in failed:
            print(col(f"    - {m['file']['name']}", "red"))
            print(col(f"      {m['file']['url']}", "dim"))
    else:
        print(col("\n  All done!", "green"))

    if len(done) >= total:
        clear_history(game, slug, kind)

# ── Settings ───────────────────────────────────────────────────────────────
def settings_menu(cfg):
    while True:
        print()
        print(col("─" * 60, "dim"))
        print(col("  Settings", "bold"))
        print(col("─" * 60, "dim"))
        k   = cfg["api_key"]
        cs  = cfg.get("cookie_string", "")
        mode = cfg.get("mode", "cookie").upper()
        oiv = "True" if cfg.get("open_in_vortex", True) else "False"
        print(f"  1. Download Mode    : {col(mode, 'green')}")
        print(f"  2. API Key          : {col((k[:8]+'...' if k else 'NOT SET'), 'yellow')}")
        print(f"  3. Cookie string    : {col(('set (' + str(len(cs)) + ' chars)' if cs else 'NOT SET'), 'yellow')}")
        print(f"  4. Open in Vortex   : {col(oiv, 'cyan')} (API Mode only)")
        print(f"  5. Pause between DL : {col(str(cfg['pause_between'])+'s', 'cyan')}")
        print(f"  6. DL Speed (MB/s)  : {col(str(cfg['download_speed_mbps']), 'cyan')}")
        print(f"  7. Clear cookie (re-paste next run)")
        print(f"  8. Back")
        print()
        ch = input("  Choice: ").strip()
        if ch == "1":
            cfg["mode"] = "api" if cfg.get("mode", "cookie") == "cookie" else "cookie"
        elif ch == "2":
            cfg["api_key"] = input("  New API Key: ").strip()
        elif ch == "3":
            cfg["cookie_string"] = input("  Paste Cookie value: ").strip()
            global _cookie_jar; _cookie_jar = None
        elif ch == "4":
            cfg["open_in_vortex"] = not cfg.get("open_in_vortex", True)
        elif ch == "5":
            try: cfg["pause_between"] = int(input("  Pause (s): ").strip())
            except ValueError: print(col("  Invalid.", "red")); continue
        elif ch == "6":
            try: cfg["download_speed_mbps"] = float(input("  Speed (MB/s): ").strip())
            except ValueError: print(col("  Invalid.", "red")); continue
        elif ch == "7":
            cfg["cookie_string"] = ""
            _cookie_jar = None
            print(col("  Cookie cleared.", "yellow"))
        elif ch == "8":
            break
        save_config(cfg)
        print(col("  Saved.", "green"))

# ── Main ───────────────────────────────────────────────────────────────────
def run_download(cfg):
    print()
    url = input(col("  Paste collection URL\n  > ", "bold")).strip()
    game, slug, revision = parse_url(url)
    if not game:
        print(col("  Bad URL. Example:\n  https://www.nexusmods.com/games/cyberpunk2077/collections/iszwwe", "red"))
        return

    print(col(f"\n  Game: {game}  |  Slug: {slug}  |  Rev: {revision or 'latest'}", "dim"))

    mods = fetch_mods(slug, revision, cfg["api_key"])
    if not mods:
        return

    mandatory = [m for m in mods if not m["optional"]]
    optional  = [m for m in mods if m["optional"]]

    print(col(f"\n  Found {len(mods)} mods  ({len(mandatory)} mandatory, {len(optional)} optional)", "green"))
    print()
    print(f"  1. All mods          ({len(mods)})")
    print(f"  2. Mandatory only    ({len(mandatory)})")
    print(f"  3. Optional only     ({len(optional)})")
    print(f"  4. Cancel")
    print()
    ch = input("  Choice: ").strip()
    if   ch == "1": download_mods(mandatory + optional, game, slug, "all",       cfg)
    elif ch == "2": download_mods(mandatory,            game, slug, "mandatory", cfg)
    elif ch == "3": download_mods(optional,             game, slug, "optional",  cfg)
    else: print(col("  Cancelled.", "dim"))

def main():
    os.system("cls" if os.name == "nt" else "clear")
    print(col("""
  ███╗   ██╗██████╗  ██████╗
  ████╗  ██║██╔══██╗██╔════╝
  ██╔██╗ ██║██║  ██║██║
  ██║╚██╗██║██║  ██║██║
  ██║ ╚████║██████╔╝╚██████╗
  ╚═╝  ╚═══╝╚═════╝  ╚═════╝
  Nexus Download Collection  v3.0  (Python)
  [Made by SahiDemon]
""", "cyan"))

    is_new_user = not CONFIG_FILE.exists()
    cfg = load_config()

    if is_new_user or not cfg.get("api_key") or not cfg.get("cookie_string"):
        print(col("─" * 60, "dim"))
        print(col("  Guided Setup for New User", "bold"))
        print(col("─" * 60, "dim"))

        # 1. API Key
        if not cfg.get("api_key"):
            print(col("\n  1. NexusMods API Key", "bold"))
            print("     Get one at: https://www.nexusmods.com/users/myaccount?tab=api")
            cfg["api_key"] = input("     Paste API Key: ").strip()

        # 2. Cookie String
        if not cfg.get("cookie_string"):
            print(col("\n  2. Cookie String", "bold"))
            print("     Required for Cookie Mode (Cloudflare bypass).")
            print("     Press Enter to try auto-extracting from your browser later,")
            print("     or paste your cookie value now:")
            cfg["cookie_string"] = input("     Paste Cookie value: ").strip()

        # 3. Select Mode
        if not cfg.get("mode") or is_new_user:
            print(col("\n  3. Select Default Download Mode", "bold"))
            print("     [1] Cookie Mode (Recommended - downloads via browser without Premium popup)")
            print("     [2] API Mode (Sends nxm:// links to Vortex - triggers Premium popup)")
            while True:
                mode_choice = input("     Choice [1 or 2]: ").strip()
                if mode_choice == "1":
                    cfg["mode"] = "cookie"
                    break
                elif mode_choice == "2":
                    cfg["mode"] = "api"
                    break
                else:
                    print(col("     Invalid choice.", "red"))

        save_config(cfg)
        print(col("\n  ✓ Setup completed and saved to config!", "green"))

    while True:
        print()
        print(col("─" * 60, "dim"))
        print(col("  Main Menu", "bold"))
        print(col("─" * 60, "dim"))
        print("  1. Download a collection")
        print("  2. Settings")
        print("  3. Exit")
        print()
        ch = input("  Choice: ").strip()
        if   ch == "1": run_download(cfg)
        elif ch == "2": settings_menu(cfg)
        elif ch == "3": print(col("\n  Goodbye!\n", "dim")); break

if __name__ == "__main__":
    main()
