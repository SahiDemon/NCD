import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

try:
    import msvcrt
    _HAS_MSVCRT = True
except ImportError:
    _HAS_MSVCRT = False

def _open_url(url):
    if os.name == "nt":
        try:
            import subprocess
            subprocess.Popen(
                ["cmd.exe", "/c", "start", "", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
        except Exception:
            ctypes.windll.shell32.ShellExecuteW(None, "open", url, None, None, 0)
    else:
        import webbrowser
        webbrowser.open(url)

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
_ensure("rich")

import requests
import browser_cookie3
from curl_cffi import requests as cffi_requests
try:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    from rich.console import Group
    from rich import box
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

import requests
import browser_cookie3
from curl_cffi import requests as cffi_requests

class SessionExpiredError(Exception):
    pass

# ── Hotkey control flags ────────────────────────────────────────────────────
_stop_flag  = threading.Event()   # Q = stop after current mod
_pause_flag = threading.Event()   # P = pause/resume
_cancel_watcher = threading.Event()  # Cancels background watcher thread

def _hotkey_listener():
    if not _HAS_MSVCRT:
        return
    while not _stop_flag.is_set():
        if msvcrt.kbhit():
            try:
                key = msvcrt.getch().decode("utf-8", errors="ignore").lower()
            except Exception:
                key = ""
            if key == "q":
                _stop_flag.set()
                print(col("\n  [Q] Stopping after this mod...", "yellow"), flush=True)
            elif key == "p":
                if _pause_flag.is_set():
                    _pause_flag.clear()
                    print(col("\n  [P] Resumed.", "green"), flush=True)
                else:
                    _pause_flag.set()
                    print(col("\n  [P] Paused — press P again to resume.", "yellow"), flush=True)
        time.sleep(0.05)

def _tick_sleep(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if _stop_flag.is_set():
            return
        while _pause_flag.is_set() and not _stop_flag.is_set():
            time.sleep(0.1)
        time.sleep(0.1)

# ── Thread-shielded curl_cffi wrappers ─────────────────────────────────────
def _cffi_get(url, **kwargs):
    result, exc = [None], [None]
    def _run():
        try:
            result[0] = cffi_requests.get(url, **kwargs)
        except Exception as e:
            exc[0] = e
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join()
    if exc[0]:
        raise exc[0]
    return result[0]

def _cffi_post(url, **kwargs):
    result, exc = [None], [None]
    def _run():
        try:
            result[0] = cffi_requests.post(url, **kwargs)
        except Exception as e:
            exc[0] = e
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join()
    if exc[0]:
        raise exc[0]
    return result[0]

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

def _progress_bar(sent, total, total_kb):
    bar_w   = 28
    pct     = sent / total if total else 0
    filled  = round(bar_w * pct)
    bar     = col("█" * filled, "cyan") + col("░" * (bar_w - filled), "dim")
    mb_sent = total_kb / 1024
    size_str = f"{mb_sent / 1024:.2f} GB" if mb_sent >= 1024 else f"{mb_sent:.1f} MB"
    pct_str  = col(f"{pct*100:.0f}%", "bold")
    print(f"  {bar}  {col(str(sent), 'cyan')}/{total}  {pct_str}  {col(size_str + ' sent', 'dim')}")
    print()

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
        "vortex_dl_path":      "",   # auto-detected if empty
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

# ── Vortex download path detection ────────────────────────────────────────
VORTEX_APPDATA = Path(os.environ.get("APPDATA", "")) / "Vortex"

def _find_vortex_dl_path(game_domain):
    r"""
    Auto-detect Vortex's download folder for a game by reading its state
    JSON files. Falls back to the default AppData\Vortex\downloads\{game}.
    Returns a Path or None.
    """
    # Candidate state files Vortex might store download path in
    candidates = [
        VORTEX_APPDATA / "state" / "persistent" / "settings.json",
        VORTEX_APPDATA / "state" / "settings.json",
        VORTEX_APPDATA / "settings.json",
    ]
    for f in candidates:
        try:
            if not f.exists():
                continue
            state = json.loads(f.read_text("utf-8"))
            # Try common key structures Vortex uses
            for path_val in [
                state.get("downloads", {}).get("path"),
                state.get("gameMode", {}).get(game_domain, {}).get("downloadPath"),
                state.get("downloadPath"),
            ]:
                if path_val:
                    p = Path(path_val) / game_domain
                    if p.exists():
                        return p
                    # Try without game subfolder
                    p2 = Path(path_val)
                    if p2.exists():
                        return p2
        except Exception:
            pass

    # Default path
    default = VORTEX_APPDATA / "downloads" / game_domain
    return default if default.exists() else None

def _watch_vortex_download(dl_dir, mod_name, expected_kb, timeout=300, state_dict=None):
    """
    Watch dl_dir for a new file whose size matches expected_kb (within 5%).
    Updates state_dict silently when provided, or prints inline bar otherwise.
    """
    if dl_dir is None or not dl_dir.exists():
        return False, 0.0

    expected_bytes = expected_kb * 1024
    before = {f: f.stat().st_size for f in dl_dir.iterdir()
              if f.suffix.lower() in (".zip", ".7z", ".rar", ".fomod", "")}
    deadline  = time.monotonic() + timeout
    start_t   = None   # set when we first see the file appear
    tracking  = None
    bar_w     = 20
    last_line = ""

    while time.monotonic() < deadline and not _stop_flag.is_set() and not _cancel_watcher.is_set():
        try:
            current = {f: f.stat().st_size for f in dl_dir.iterdir()
                       if f.suffix.lower() in (".zip", ".7z", ".rar", ".fomod", "", ".part")}
        except Exception:
            time.sleep(0.5)
            continue

        # Find the file that appeared after our snapshot
        new_files = {f: s for f, s in current.items() if f not in before or current[f] > before.get(f, 0)}

        if not new_files:
            time.sleep(0.5)
            continue

        # Pick the largest growing file as ours
        tracking = max(new_files, key=lambda f: current[f])
        cur_bytes = current[tracking]
        if start_t is None:
            start_t = time.monotonic()

        cur_mb = cur_bytes / 1024 / 1024
        exp_mb = expected_bytes / 1024 / 1024 if expected_bytes > 0 else 0
        pct = min(cur_bytes / expected_bytes, 1.0) if expected_bytes > 0 else 0
        elapsed = time.monotonic() - start_t if start_t else 0
        speed = (cur_bytes / 1024 / 1024) / elapsed if elapsed > 0 else 0

        if state_dict is not None:
            state_dict["cur_mb"] = cur_mb
            state_dict["exp_mb"] = exp_mb
            state_dict["pct"]    = pct
            state_dict["speed"]  = speed
        else:
            if expected_bytes > 0:
                filled = round(bar_w * pct)
                bar    = col("█" * filled, "cyan") + col("░" * (bar_w - filled), "dim")
                line   = f"\r    {col('⬇', 'cyan')} {bar}  {cur_mb:.1f}/{exp_mb:.1f} MB  {col(f'{pct*100:.0f}%', 'bold')}"
            else:
                line   = f"\r    {col('⬇', 'cyan')}  {cur_mb:.1f} MB received..."
            if line != last_line:
                print(line, end="", flush=True)
                last_line = line

        # Done when file size matches expected
        if expected_bytes > 0 and cur_bytes >= expected_bytes * 0.95:
            if state_dict is None:
                print(f"\r    {col('✓ Downloaded', 'green')}  {col(f'{speed:.1f} MB/s measured', 'dim')}" + " " * 20)
            return True, speed

        time.sleep(0.5)

    if last_line:
        print()
    return False, 0.0

# ── Cookie jar ─────────────────────────────────────────────────────────────
_cookie_jar = None

# NexusMods cookies that indicate a valid logged-in session
_KEY_COOKIES = {"nexusmods_session", "nexusmods_session_refresh", "cf_clearance", "sid", "member_id"}

# All browsers browser_cookie3 supports on Windows (in priority order)
_BROWSERS = [
    ("Chrome",   browser_cookie3.chrome),
    ("Edge",     browser_cookie3.edge),
    ("Brave",    browser_cookie3.brave),
    ("Firefox",  browser_cookie3.firefox),
    ("Opera",    browser_cookie3.opera),
    ("Opera GX", browser_cookie3.opera_gx),
    ("Vivaldi",  browser_cookie3.vivaldi),
    ("Chromium", browser_cookie3.chromium),
]

def _jar_from_string(cookie_str):
    jar = requests.cookies.RequestsCookieJar()
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            name, _, value = part.partition("=")
            jar.set(name.strip(), value.strip(), domain=".nexusmods.com", path="/")
    return jar

def _to_requests_jar(jar):
    if isinstance(jar, requests.cookies.RequestsCookieJar):
        return jar
    rjar = requests.cookies.RequestsCookieJar()
    for cookie in jar:
        rjar.set_cookie(cookie)
    return rjar

def _is_valid_session(jar):
    _LOGIN_COOKIES = {"nexusmods_session", "nexusmods_session_refresh", "member_id"}
    names = {c.name for c in jar}
    return bool(names & _LOGIN_COOKIES)

def _check_cookie_freshness(cookie_str):
    if not cookie_str:
        return True, ""
    m = re.search(r'cf_clearance=([^;]+)', cookie_str)
    if not m:
        return True, ""
    parts = m.group(1).split("-")
    # Find first numeric segment that looks like a unix timestamp (10 digits)
    for part in parts:
        if part.isdigit() and len(part) == 10:
            issued = int(part)
            age_min = (time.time() - issued) / 60
            if age_min > 55:
                return False, f"cf_clearance is {age_min:.0f} min old — likely expired (limit ~60 min)"
            elif age_min > 40:
                return True, f"cf_clearance is {age_min:.0f} min old — consider refreshing soon"
            return True, ""
    return True, ""

def _verify_session_live(jar):
    try:
        cookies = {c.name: c.value for c in jar}
        r = _cffi_get(
            "https://www.nexusmods.com/users/myaccount",
            cookies=cookies,
            headers={"Accept": "text/html"},
            impersonate="chrome136",
            allow_redirects=False,
            timeout=10,
        )
        # 200 = logged-in account page  |  302 = redirect to login page
        return r.status_code == 200
    except Exception:
        return False

def _try_browser_cookies():
    for name, loader in _BROWSERS:
        try:
            jar = loader(domain_name=".nexusmods.com")
            if not {c.name: c.value for c in jar} or not _is_valid_session(jar):
                continue
            jar = _to_requests_jar(jar)
            if _verify_session_live(jar):
                return name, jar
        except Exception:
            continue
    return None, None

def get_cookie_jar(cfg):
    global _cookie_jar
    if _cookie_jar is not None:
        return _cookie_jar

    # 1. Silently try browser auto-detection
    browser_name, jar = _try_browser_cookies()
    if jar is not None:
        if _HAS_RICH:
            Console().print(Panel(f"[bold green]✓ Valid NexusMods Session Detected[/bold green] via [bold white]{browser_name}[/bold white]", title="[bold cyan]Authentication Status[/bold cyan]", subtitle="[bold cyan]★ NDC by SahiDemon ★[/bold cyan]", border_style="green", padding=(0, 2)))
        else:
            print(col(f"  ✓ Session detected ({browser_name})", "green"))
        try:
            cfg["cookie_string"] = "; ".join(f"{c.name}={c.value}" for c in jar)
            save_config(cfg)
        except Exception:
            pass
        _cookie_jar = jar
        return jar

    # 2. Silently try saved cookie string
    if cfg.get("cookie_string"):
        jar = _jar_from_string(cfg["cookie_string"])
        if _verify_session_live(jar):
            if _HAS_RICH:
                Console().print(Panel("[bold green]✓ Valid NexusMods Session Detected[/bold green] (Saved Cookie)", title="[bold cyan]Authentication Status[/bold cyan]", subtitle="[bold cyan]★ NDC by SahiDemon ★[/bold cyan]", border_style="green", padding=(0, 2)))
            else:
                print(col("  ✓ Session detected (Saved Cookie)", "green"))
            _cookie_jar = jar
            return jar
        else:
            cfg["cookie_string"] = ""
            save_config(cfg)

    # 3. Clean Boxed Prompt for Manual Cookie String
    if _HAS_RICH:
        prompt_txt = """[bold yellow]⚠ No active NexusMods session detected (or cookie expired)[/bold yellow]

To download mods directly from NexusMods:
  1. Log into [bold cyan]nexusmods.com[/bold cyan] in your web browser
  2. Press [bold white]F12[/bold white] → [bold white]Network[/bold white] tab → press [bold white]F5[/bold white] to refresh
  3. Click any request to [dim]nexusmods.com[/dim] → copy the [bold white]Cookie[/bold white] request header"""
        Console().print(Panel(prompt_txt, title="[bold yellow]Authentication Required[/bold yellow]", subtitle="[bold cyan]★ NDC by SahiDemon ★[/bold cyan]", border_style="yellow", padding=(1, 2)))
    else:
        print(col("\n  ⚠ No active NexusMods session detected. Please paste Cookie string:", "yellow"))

    cookie_str = input(col("  Paste Cookie value (or Enter to cancel) › ", "bold")).strip()
    if not cookie_str:
        return None

    jar = _jar_from_string(cookie_str)
    cfg["cookie_string"] = cookie_str
    save_config(cfg)
    _cookie_jar = jar
    return jar
    return jar

# ── GraphQL mod list ───────────────────────────────────────────────────────
QUERY = """
query CollectionRevisionMods($revision:Int,$slug:String!,$viewAdultContent:Boolean){
  collectionRevision(revision:$revision,slug:$slug,viewAdultContent:$viewAdultContent){
    revision
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
        return [], None

    actual_rev = cr.get("revision") or revision
    mods = cr["modFiles"]
    for m in mods:
        d   = m["file"]["mod"]["game"]["domainName"]
        mid = m["file"]["mod"]["modId"]
        fid = m["file"]["fileId"]
        m["file"]["url"] = f"https://www.nexusmods.com/{d}/mods/{mid}?tab=files&file_id={fid}"
    return mods, actual_rev

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

    # ── Step 1: HTML scrape ────────────────────────────────────────────────
    try:
        r = _cffi_get(
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
                    if url and ("nxm://" in url or "nexus-cdn.com" in url):
                        if "nxm://" in url and "key=" not in url:
                            break
                        return url
    except Exception as e:
        err = str(e)
        # Suppress interrupt-caused curl noise
        if "curl: (23)" not in err and "KeyboardInterrupt" not in err:
            print(col(f"    [WARN] HTML scrape: {err}", "yellow"))

    # ── Step 2 & 3: GenerateDownloadUrl API ───────────────────────────────
    for nmm in (True, False):
        body = f"fid={fid}&game_id={game_id}" + ("&nmm=1" if nmm else "")
        try:
            r = _cffi_post(
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
                raise SessionExpiredError("403 from NexusMods — session expired mid-run")
        except Exception as e:
            err = str(e)
            if "curl: (23)" not in err and "KeyboardInterrupt" not in err:
                print(col(f"    [WARN] API: {err}", "yellow"))

    return ""

# ── REST API Download Link (API Mode) ──────────────────────────────────────
NEXUS_API = "https://api.nexusmods.com/v1"

def fetch_download_link(mod, api_key):
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
def download_mods(mods, game, slug, kind, cfg, revision=None):
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

    failed  = []
    pad_w   = len(str(total))
    sent_n  = 0
    sent_kb = 0

    # Resolve Vortex download folder (once per session)
    dl_dir = _resolve_dl_dir(game, cfg)
    # ── Pre-populate done from disk (verify-then-skip) ────────────────────
    if dl_dir:
        disk_ids = _scan_downloaded_mod_ids(dl_dir)
        pre_skip = 0
        for mod in mods:
            mid = mod["file"]["mod"]["modId"]
            fid = mod["fileId"]
            if mid in disk_ids and fid not in done:
                done.add(fid)
                pre_skip += 1
        if pre_skip:
            save_history(game, slug, kind, done)
            print(col(f"  ✓ {pre_skip} mod(s) already on disk — auto-skipped.", "green"))
    else:
        print(col("  ⚠ Vortex download folder not found — live tracking disabled.", "yellow"))
        print(col("    Set it manually in Settings → 6.", "dim"))

    if dl_dir:
        print(col(f"  ⬇ Watching: {dl_dir}", "dim"))

    speed_tuned = False   # True after first auto-tune measurement

    # ── Rich Live Dashboard Helper ────────────────────────────────────────
    def _render_dashboard(mods_list, active_idx, state_dict, sent_n, total_n, sent_kb):
        if not _HAS_RICH:
            return ""
        # 1. Mod status table (windowed around active_idx)
        t = Table(box=box.ROUNDED, expand=True, border_style="cyan")
        t.add_column("#", width=6, justify="right", style="dim")
        t.add_column("Mod Name", style="bold white", ratio=1)
        t.add_column("Size", width=10, justify="right")
        t.add_column("Status", width=12, justify="center")
        t.add_column("Speed", width=12, justify="right")

        start_r = max(0, min(active_idx - 5, len(mods_list) - 10))
        end_r   = min(len(mods_list), start_r + 11)
        for row_i in range(start_r, end_r):
            m_item = mods_list[row_i]
            st = m_item["status"]
            if st == "DONE":
                st_str = "[bold green]✓ DONE[/bold green]"
            elif st == "SKIP":
                st_str = "[dim]⏭ SKIP[/dim]"
            elif st == "ACTIVE":
                st_str = "[bold cyan]⬇ ACTIVE[/bold cyan]"
            elif st == "FAIL":
                st_str = "[bold red]✗ FAILED[/bold red]"
            else:
                st_str = "[dim]⏳ QUEUED[/dim]"
            t.add_row(m_item["label"], m_item["name"][:40], m_item["size_str"], st_str, m_item["speed"])

        # 2. Active mod progress panel
        if state_dict and state_dict.get("active"):
            pct = state_dict.get("pct", 0)
            bw = 28
            f_cnt = round(bw * pct)
            p_bar = "█" * f_cnt + "░" * (bw - f_cnt)
            spd = state_dict.get("speed", 0)
            p_txt = f"[bold cyan]{state_dict.get('name', '')[:45]}[/bold cyan]   [cyan]{p_bar}[/cyan]  {state_dict.get('cur_mb', 0):.1f}/{state_dict.get('exp_mb', 0):.1f} MB ({pct*100:.0f}%)   [yellow]{spd:.1f} MB/s[/yellow]"
        else:
            p_txt = "[dim]Waiting for next download...[/dim]"
        act_panel = Panel(p_txt, title="[bold cyan]Active Download[/bold cyan]", border_style="cyan")

        # 3. Overall footer
        ov_pct = sent_n / total_n if total_n > 0 else 0
        fw = 30
        fcnt = round(fw * ov_pct)
        fbar = "█" * fcnt + "░" * (fw - fcnt)
        foot_txt = f"Overall: [green]{fbar}[/green]  {sent_n}/{total_n} Mods ({ov_pct*100:.0f}%)\n[dim]Q = Stop after current  |  P = Pause/Resume  |  Folder: {dl_dir}[/dim]"
        foot_panel = Panel(foot_txt, title=f"[bold white]{game}  │  {slug}  │  ★ NDC by SahiDemon ★[/bold white]", border_style="blue")

        return Group(t, act_panel, foot_panel)

    # Prepare status rows for dashboard
    mods_list = []
    for idx, m in enumerate(mods, 1):
        sz = m["file"].get("size") or 0
        mods_list.append({
            "label": f"{idx}/{total}",
            "name": m["file"]["name"],
            "size_str": convert_size(sz),
            "status": "SKIP" if m["fileId"] in done else "QUEUED",
            "speed": ""
        })

    # Reset and start hotkey listener
    _stop_flag.clear()
    _pause_flag.clear()
    hl = threading.Thread(target=_hotkey_listener, daemon=True)
    hl.start()

    skipped_count = sum(1 for m in mods if m["fileId"] in done)

    if _HAS_RICH:
        rconsole = Console()
        state_dict = {"active": False, "name": "", "cur_mb": 0.0, "exp_mb": 0.0, "pct": 0.0, "speed": 0.0}
        with Live(_render_dashboard(mods_list, 0, state_dict, sent_n, total, sent_kb), refresh_per_second=4, console=rconsole) as live:
            for idx, mod in enumerate(mods, 1):
                if _stop_flag.is_set():
                    break
                while _pause_flag.is_set() and not _stop_flag.is_set():
                    time.sleep(0.1)

                fid   = mod["fileId"]
                size  = mod["file"].get("size") or 0
                name  = mod["file"]["name"]

                if fid in done:
                    sent_n  += 1
                    sent_kb += size
                    mods_list[idx-1]["status"] = "SKIP"
                    live.update(_render_dashboard(mods_list, idx-1, state_dict, sent_n, total, sent_kb))
                    continue

                mods_list[idx-1]["status"] = "ACTIVE"
                state_dict.update({"active": True, "name": name, "cur_mb": 0.0, "exp_mb": size/1024, "pct": 0.0, "speed": 0.0})
                live.update(_render_dashboard(mods_list, idx-1, state_dict, sent_n, total, sent_kb))

                try:
                    url = fetch_keyed_nxm(mod, jar) if mode == "cookie" else fetch_download_link(mod, cfg["api_key"])
                except Exception:
                    url = ""

                if not url:
                    failed.append(mod)
                    mods_list[idx-1]["status"] = "FAIL"
                    continue

                _open_url(url)
                sent_n  += 1
                sent_kb += size
                done.add(fid)
                save_history(game, slug, kind, done)

                if idx < total and not _stop_flag.is_set():
                    smart = round(size / 1024 / speed_mbps) + pause_extra if (pause_extra > 0 and size > 0 and speed_mbps > 0) else pause_extra
                    if smart > 0 and url and dl_dir:
                        _cancel_watcher.clear()
                        w_res = [False, 0.0]
                        def _watcher_target(res=w_res):
                            res[0], res[1] = _watch_vortex_download(dl_dir, name, size, smart + 30, state_dict=state_dict)
                        watcher = threading.Thread(target=_watcher_target, daemon=True)
                        watcher.start()
                        end_t = time.monotonic() + smart
                        while time.monotonic() < end_t and not _stop_flag.is_set():
                            live.update(_render_dashboard(mods_list, idx-1, state_dict, sent_n, total, sent_kb))
                            time.sleep(0.2)
                        _cancel_watcher.set()
                        if not speed_tuned and w_res[0] and w_res[1] > 0.1 and size > 500:
                            speed_mbps = round(w_res[1], 2)
                            cfg["download_speed_mbps"] = speed_mbps
                            save_config(cfg)
                            speed_tuned = True
                        if w_res[1] > 0:
                            mods_list[idx-1]["speed"] = f"{w_res[1]:.1f} MB/s"

                mods_list[idx-1]["status"] = "DONE"
                state_dict["active"] = False
                live.update(_render_dashboard(mods_list, idx-1, state_dict, sent_n, total, sent_kb))
    else:
        # Fallback console mode
        for idx, mod in enumerate(mods, 1):
            if _stop_flag.is_set(): break
            fid = mod["fileId"]
            if fid in done:
                sent_n += 1; sent_kb += (mod["file"].get("size") or 0)
                continue
            # standard print
            url = fetch_keyed_nxm(mod, jar) if mode == "cookie" else fetch_download_link(mod, cfg["api_key"])
            if url:
                _open_url(url)
                done.add(fid)
                save_history(game, slug, kind, done)
                time.sleep(cfg["pause_between"])

    _cancel_watcher.set()
    print(col("─" * 60, "dim"))

    # ── Auto-retry failed mods once ────────────────────────────────────────
    if failed and not _stop_flag.is_set():
        print(col(f"\n  ↻ Auto-retrying {len(failed)} failed mod(s)...", "yellow"))
        time.sleep(3)
        still_failed = []
        for mod in failed:
            name  = mod["file"]["name"]
            size  = mod["file"].get("size") or 0
            fid   = mod["fileId"]
            print(col(f"    Retry: {name}", "dim"), end="", flush=True)
            try:
                url = fetch_keyed_nxm(mod, jar) if mode == "cookie" else fetch_download_link(mod, cfg["api_key"])
            except Exception:
                url = ""
            if url:
                _open_url(url)
                done.add(fid)
                save_history(game, slug, kind, done)
                print(col("  ✓", "green"))
            else:
                still_failed.append(mod)
                print(col("  ✗ still failed", "red"))
        failed = still_failed

    if failed:
        print(col(f"\n  {len(failed)} mod(s) could not be downloaded:", "red"))
        for m in failed:
            print(col(f"    ✗ {m['file']['name']}", "red"))
            print(col(f"      {m['file']['url']}", "dim"))
    else:
        print(col("\n  ✓ All done!", "green"))
        if revision and not _stop_flag.is_set():
            coll_nxm = f"nxm://{game}/collections/{slug}/revisions/{revision}"
            print(col(f"  ★ Launching collection installer in Vortex:\n    → {coll_nxm}\n", "cyan"))
            _open_url(coll_nxm)

    if len(done) >= total:
        clear_history(game, slug, kind)

# ── Settings ───────────────────────────────────────────────────────────────
def _s_row(num, label, value, value_col, desc=""):
    num_s   = col(f" {num} ", "bold")
    label_s = f"{label:<22}"
    val_s   = col(value, value_col)
    row     = f"  │ {num_s} │ {label_s} {val_s}"
    print(row)
    if desc:
        print(f"  │     │ {col('  ' + desc, 'dim')}")

def settings_menu(cfg):
    while True:
        os.system("cls" if os.name == "nt" else "clear")
        k    = cfg.get("api_key", "")
        cs   = cfg.get("cookie_string", "")
        mode = cfg.get("mode", "cookie")
        vdp  = cfg.get("vortex_dl_path", "")

        vdp_display = vdp[:40] + "..." if len(vdp) > 40 else (vdp or "auto-detect")

        if _HAS_RICH:
            rconsole = Console()
            st_table = Table(box=box.ROUNDED, expand=True, border_style="cyan", title="[bold cyan]⚙ NDC Configuration & Settings[/bold cyan]")
            st_table.add_column("#", justify="center", width=4, style="bold yellow")
            st_table.add_column("Setting", style="bold white", width=18)
            st_table.add_column("Current Status", width=22)
            st_table.add_column("Description", style="dim white")

            mode_str = "[bold green]● COOKIE (Free)[/bold green]" if mode == "cookie" else "[bold yellow]● API (Premium)[/bold yellow]"
            api_str  = f"[green]✓ {k[:8]}...[/green]" if k else "[bold red]✗ NOT SET[/bold red]"
            ck_str   = f"[green]✓ SET ({len(cs)} chars)[/green]" if cs else "[bold red]✗ NOT SET[/bold red]"

            st_table.add_row("1", "Download Mode", mode_str, "Cookie = free downloads │ API = requires Premium")
            st_table.add_row("2", "Nexus API Key", api_str, "Required to fetch collection mod lists")
            st_table.add_row("3", "Cookie String", ck_str, "Paste fresh cookies if downloads fail")
            st_table.add_row("4", "Pause Between DL", f"[cyan]{cfg['pause_between']}s[/cyan]", "Wait time added between each mod send")
            st_table.add_row("5", "Your DL Speed", f"[cyan]{cfg['download_speed_mbps']} MB/s[/cyan]", "Used to estimate wait time per file size")
            st_table.add_row("6", "Vortex DL Folder", f"[cyan]{vdp_display}[/cyan]", "Leave blank to auto-detect from Vortex state")
            st_table.add_row("7", "Clear Cookies", "[dim]—[/dim]", "Wipe saved cookie string")
            st_table.add_row("8", "Back to Menu", "[dim]—[/dim]", "Return to Main Menu")

            p = Panel(st_table, title="[bold cyan]★ NDC by SahiDemon ★[/bold cyan]", border_style="cyan", padding=(1, 2))
            rconsole.print(p)
        else:
            w = 62
            print()
            print(col("  " + "╔" + "═" * (w-4) + "╗", "cyan"))
            print(col(f"  ║{'  ⚙  NDC Settings':^{w-4}}║", "cyan"))
            print(col("  " + "╚" + "═" * (w-4) + "╝", "cyan"))
            print()
            _s_row(1, "Download Mode", ("● COOKIE" if mode == "cookie" else "● API"), "green", "Cookie = free │ API = Premium")
            _s_row(2, "API Key", (k[:12] + "..." if k else "✗ NOT SET"), "green" if k else "red", "Required for mod lists")
            _s_row(3, "Cookie String", ("✓ set" if cs else "✗ NOT SET"), "green" if cs else "red", "Authentication")
            _s_row(4, "Pause Between DL", f"{cfg['pause_between']}s", "cyan", "Wait time")
            _s_row(5, "Your DL Speed", f"{cfg['download_speed_mbps']} MB/s", "cyan", "Calibration speed")
            _s_row(6, "Vortex DL Folder", vdp_display, "cyan", "Download destination")
            _s_row(7, "Clear Cookies", "wipe string", "dim")
            _s_row(8, "Back to Menu", "", "dim")

        ch = input(col("\n  Choice › ", "bold")).strip()

        if ch == "1":
            cfg["mode"] = "api" if mode == "cookie" else "cookie"
        elif ch == "2":
            v = input(col("  Paste API Key › ", "bold")).strip()
            if v: cfg["api_key"] = v
        elif ch == "3":
            v = input(col("  Paste Cookie › ", "bold")).strip()
            if v:
                cfg["cookie_string"] = v
                global _cookie_jar; _cookie_jar = None
        elif ch == "4":
            try: cfg["pause_between"] = int(input(col("  Pause (seconds) › ", "bold")).strip())
            except ValueError: pass
        elif ch == "5":
            try: cfg["download_speed_mbps"] = float(input(col("  Speed (MB/s) › ", "bold")).strip())
            except ValueError: pass
        elif ch == "6":
            cfg["vortex_dl_path"] = input(col("  Vortex Download Folder › ", "bold")).strip()
        elif ch == "7":
            cfg["cookie_string"] = ""
            _cookie_jar = None
        elif ch == "8":
            break
        save_config(cfg)
        print(col("  ✓ Saved.", "green"))
        time.sleep(0.6)

# ── Verify downloads ───────────────────────────────────────────────────────
def _resolve_dl_dir(game, cfg):
    custom_dl = cfg.get("vortex_dl_path", "").strip()
    if custom_dl:
        path = Path(custom_dl)
    else:
        path = _find_vortex_dl_path(game)

    if not path or not path.exists():
        return None

    # If the resolved path doesn't end with the game domain, but there is a subfolder with that name, append it
    if path.name.lower() != game.lower():
        sub = path / game
        if sub.exists():
            return sub

    return path

def _scan_downloaded_mod_ids(dl_dir):
    found_ids = set()
    if dl_dir is None or not dl_dir.exists():
        return found_ids
    exts = {".zip", ".7z", ".rar", ".fomod", ".tar", ".gz"}
    for f in dl_dir.iterdir():
        if f.suffix.lower() not in exts:
            continue
        # First all-digit dash-segment of 3+ chars is the mod ID
        for part in f.stem.split("-"):
            if part.isdigit() and len(part) >= 3:
                found_ids.add(int(part))
                break
    return found_ids

def verify_downloads(mods, game, cfg):
    os.system("cls" if os.name == "nt" else "clear")
    dl_dir = _resolve_dl_dir(game, cfg)

    print()
    if dl_dir and dl_dir.exists():
        print(col(f"  Scanning: {dl_dir}", "dim"))
    else:
        print(col("  ✗ Vortex download folder not found.", "red"))
        print(col("    Set it in Settings → 6 or make sure Vortex has at least one mod downloaded.", "dim"))
        return

    found_ids = _scan_downloaded_mod_ids(dl_dir)
    print(col(f"  {len(found_ids)} mod file(s) found on disk.\n", "dim"))

    ok, missing = [], []
    for mod in mods:
        mid  = mod["file"]["mod"]["modId"]
        name = mod["file"]["name"]
        size = mod["file"].get("size") or 0
        url  = mod["file"]["url"]
        if mid in found_ids:
            ok.append((name, size))
        else:
            missing.append((name, size, url))

    # ── Report ────────────────────────────────────────────────────────────
    print(col(f"  ✓ Downloaded  ({len(ok)}/{len(mods)})", "green"))
    print(col("  " + "─" * 56, "dim"))
    for name, size in ok:
        print(col(f"    ✓  {name:<40} {convert_size(size):>8}", "green"))

    if missing:
        print()
        print(col(f"  ✗ Missing  ({len(missing)}/{len(mods)})", "red"))
        print(col("  " + "─" * 56, "dim"))
        for name, size, url in missing:
            print(col(f"    ✗  {name:<40} {convert_size(size):>8}", "red"))
            print(col(f"       {url}", "dim"))

    print()
    total_ok_mb  = sum(s for _, s in ok) / 1024
    total_mis_mb = sum(s for _, s, _ in missing) / 1024
    bar_w  = 30
    pct    = len(ok) / len(mods) if mods else 0
    filled = round(bar_w * pct)
    bar    = col("█" * filled, "green") + col("░" * (bar_w - filled), "red")
    print(f"  {bar}  {len(ok)}/{len(mods)}  {col(f'{pct*100:.0f}%', 'bold')}")
    print(col(f"  {total_ok_mb:.1f} MB on disk  │  {total_mis_mb:.1f} MB still needed", "dim"))
    print()
    input(col("  Press Enter to return to menu...", "dim"))

# ── Main ───────────────────────────────────────────────────────────────────
def run_download(cfg):
    os.system("cls" if os.name == "nt" else "clear")
    print()
    url = input(col("  Paste collection URL\n  > ", "bold")).strip()
    game, slug, revision = parse_url(url)
    if not game:
        print(col("  Bad URL. Example:\n  https://www.nexusmods.com/games/cyberpunk2077/collections/iszwwe", "red"))
        input(col("  Press Enter to return...", "dim"))
        return

    print(col(f"\n  Game: {game}  |  Slug: {slug}  |  Rev: {revision or 'latest'}", "dim"))

    mods, actual_rev = fetch_mods(slug, revision, cfg["api_key"])
    if not mods:
        input(col("  Press Enter to return...", "dim"))
        return

    mandatory = [m for m in mods if not m["optional"]]
    optional  = [m for m in mods if m["optional"]]

    # Scan Vortex folder to find missing mods
    dl_dir = _resolve_dl_dir(game, cfg)
    found_ids = _scan_downloaded_mod_ids(dl_dir) if dl_dir else set()

    missing_all = [m for m in mods if m["file"]["mod"]["modId"] not in found_ids]

    os.system("cls" if os.name == "nt" else "clear")
    if _HAS_RICH:
        rconsole = Console()
        t = Table(box=box.ROUNDED, expand=True, border_style="cyan", title=f"[bold cyan]📥 Collection: {slug}[/bold cyan]")
        t.add_column("Option", justify="center", width=8, style="bold yellow")
        t.add_column("Action", style="bold white")
        t.add_column("Mod Count", justify="right", style="cyan")

        t.add_row("[1]", "Download ALL Mods", f"{len(mods)} mods")
        t.add_row("[2]", "Download Mandatory Only", f"{len(mandatory)} mods")
        t.add_row("[3]", "Download Optional Only", f"{len(optional)} mods")
        t.add_row("[4]", "[bold green]★ Download MISSING Only (Recommended)[/bold green]", f"{len(missing_all)} mods")
        t.add_row("[5]", "Verify Downloads on Disk", "Scan folder")
        t.add_row("[6]", "Cancel & Return to Menu", "—")

        meta = f"Game: [bold white]{game}[/bold white]  │  Revision: [bold white]{actual_rev or 'latest'}[/bold white]  │  Status on Disk: [green]{len(mods)-len(missing_all)}/{len(mods)}[/green]"
        rconsole.print(Panel(t, title=meta, subtitle="[bold cyan]★ NDC by SahiDemon ★[/bold cyan]", border_style="cyan", padding=(1, 2)))
    else:
        print(col(f"\n  Collection: {slug} (Game: {game} │ Rev: {actual_rev or 'latest'})", "bold"))
        print(col(f"  Found {len(mods)} mods  ({len(mandatory)} mandatory, {len(optional)} optional)", "green"))
        print(f"  1. All mods ({len(mods)})")
        print(f"  2. Mandatory ({len(mandatory)})")
        print(f"  3. Optional ({len(optional)})")
        print(f"  4. Download MISSING ({len(missing_all)})")
        print(f"  5. Verify downloads")
        print(f"  6. Cancel")

    print()
    ch = input("  Choice: ").strip()
    if   ch == "1": download_mods(mandatory + optional, game, slug, "all",       cfg, revision=actual_rev)
    elif ch == "2": download_mods(mandatory,            game, slug, "mandatory", cfg, revision=actual_rev)
    elif ch == "3": download_mods(optional,             game, slug, "optional",  cfg, revision=actual_rev)
    elif ch == "4": download_mods(missing_all,          game, slug, "missing",   cfg, revision=actual_rev)
    elif ch == "5": verify_downloads(mods, game, cfg)
    else: print(col("  Cancelled.", "dim"))

    input(col("\n  Press Enter to return to Main Menu...", "dim"))

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

    if is_new_user or not cfg.get("api_key"):
        os.system("cls" if os.name == "nt" else "clear")

        if _HAS_RICH:
            c = Console()
            c.print(Panel(
                "[bold cyan]Welcome to NDC![/bold cyan]\n\n"
                "This is a one-time setup. We'll get you configured in under a minute.\n"
                "You can change any of these later in [bold white]Settings[/bold white].",
                title="[bold cyan]First-Time Setup[/bold cyan]",
                subtitle="[bold cyan]★ NDC by SahiDemon ★[/bold cyan]",
                border_style="cyan", padding=(1, 2)
            ))
        else:
            print(col("\n  ★ First-Time Setup ★\n", "cyan"))

        # ── Step 1: API Key ────────────────────────────────────────────────
        if _HAS_RICH:
            c.print(Panel(
                "[bold white]Step 1 of 3 — NexusMods API Key[/bold white]\n\n"
                "Required to fetch the list of mods in any collection.\n"
                "Get yours at: [bold cyan]nexusmods.com/users/myaccount?tab=api[/bold cyan]",
                border_style="yellow", padding=(1, 2)
            ))
        else:
            print(col("  Step 1: API Key", "yellow"))
            print("  Get one at: nexusmods.com/users/myaccount?tab=api")

        cfg["api_key"] = input(col("  Paste API Key › ", "bold")).strip()

        # ── Step 2: Mode selection ─────────────────────────────────────────
        os.system("cls" if os.name == "nt" else "clear")
        if _HAS_RICH:
            c = Console()
            mode_table = Table(box=box.ROUNDED, expand=True, border_style="cyan", title="[bold white]Step 2 of 3 — Download Mode[/bold white]")
            mode_table.add_column("#", justify="center", width=4, style="bold yellow")
            mode_table.add_column("Mode", style="bold white", width=18)
            mode_table.add_column("How it works", style="dim white")
            mode_table.add_row("1", "Cookie Mode  ★", "Uses your browser login session — works without Premium")
            mode_table.add_row("2", "API Mode", "Uses the official API — requires a Premium account for direct downloads")
            c.print(Panel(mode_table, subtitle="[bold cyan]★ NDC by SahiDemon ★[/bold cyan]", border_style="cyan", padding=(1, 2)))
        else:
            print(col("\n  Step 2: Download Mode\n  1. Cookie Mode (recommended — no Premium needed)\n  2. API Mode (requires Premium)", "bold"))

        mode_ch = input(col("  Choice [1/2, default=1] › ", "bold")).strip()
        cfg["mode"] = "api" if mode_ch == "2" else "cookie"

        # ── Step 3: Cookie capture (only for cookie mode) ──────────────────
        if cfg["mode"] == "cookie":
            os.system("cls" if os.name == "nt" else "clear")
            if _HAS_RICH:
                c = Console()
                c.print(Panel(
                    "[bold white]Step 3 of 3 — NexusMods Session Cookies[/bold white]\n\n"
                    "Trying to auto-detect your browser session...",
                    border_style="cyan", padding=(1, 2)
                ))
            else:
                print(col("\n  Step 3: Detecting browser cookies...", "cyan"))

            browser_name, jar = _try_browser_cookies()
            if jar is not None:
                cfg["cookie_string"] = "; ".join(f"{c.name}={c.value}" for c in jar)
                if _HAS_RICH:
                    Console().print(Panel(
                        f"[bold green]✓ Session found via {browser_name}![/bold green]\n\n"
                        "Your cookies have been saved automatically.\n"
                        "You won't need to paste anything manually.",
                        border_style="green", padding=(1, 2)
                    ))
                else:
                    print(col(f"  ✓ Session detected from {browser_name}!", "green"))
                time.sleep(2)
            else:
                if _HAS_RICH:
                    Console().print(Panel(
                        "[bold yellow]⚠ Could not auto-detect a browser session[/bold yellow]\n\n"
                        "To get your Cookie string:\n"
                        "  1. Log into [bold cyan]nexusmods.com[/bold cyan] in your browser\n"
                        "  2. Press [bold white]F12[/bold white] → Network tab → press [bold white]F5[/bold white]\n"
                        "  3. Click any request → copy the [bold white]Cookie[/bold white] request header\n\n"
                        "[dim]You can also skip this and paste it later in Settings → 3[/dim]",
                        title="[bold yellow]Manual Cookie Entry[/bold yellow]",
                        border_style="yellow", padding=(1, 2)
                    ))
                else:
                    print(col("\n  ⚠ Auto-detect failed. Paste your NexusMods cookie string:", "yellow"))

                cookie_str = input(col("  Paste Cookie (or press Enter to skip) › ", "bold")).strip()
                if cookie_str:
                    cfg["cookie_string"] = cookie_str
        else:
            cfg["cookie_string"] = ""

        save_config(cfg)
        os.system("cls" if os.name == "nt" else "clear")
        if _HAS_RICH:
            Console().print(Panel(
                "[bold green]✓ Setup Complete![/bold green]\n\n"
                f"Mode:  [bold white]{'Cookie (free downloads)' if cfg['mode'] == 'cookie' else 'API (Premium)'}[/bold white]\n"
                f"Cookies: [bold white]{'Saved ✓' if cfg.get('cookie_string') else 'Not set (can add in Settings)'}[/bold white]\n\n"
                "You're ready to start downloading collections!",
                title="[bold cyan]All Done[/bold cyan]",
                subtitle="[bold cyan]★ NDC by SahiDemon ★[/bold cyan]",
                border_style="green", padding=(1, 2)
            ))
        else:
            print(col("  ✓ Setup done!\n", "green"))
        time.sleep(2)


    while True:
        os.system("cls" if os.name == "nt" else "clear")
        if _HAS_RICH:
            rconsole = Console()
            logo = """[bold cyan]
       ███╗   ██╗██████╗  ██████╗
       ████╗  ██║██╔══██╗██╔════╝
       ██╔██╗ ██║██║  ██║██║
       ██║╚██╗██║██║  ██║██║
       ██║ ╚████║██████╔╝╚██████╗
       ╚═╝  ╚═══╝╚═════╝  ╚═════╝
     Nexus Download Collection  v3.0
         ★ NDC by SahiDemon ★[/bold cyan]"""
            t = Table(box=box.ROUNDED, expand=True, border_style="cyan")
            t.add_column("Option", justify="center", width=8, style="bold yellow")
            t.add_column("Menu Action", style="bold white")
            t.add_column("Description", style="dim white")
            t.add_row("[1]", "📥 Download a Collection", "Fetch & install Nexus collection mod packs")
            t.add_row("[2]", "⚙  Settings & Configuration", "API Key, Cookies, Download Speed, Vortex Folder")
            t.add_row("[3]", "❌ Exit Application", "Close NDC")
            rconsole.print(Panel(Group(logo, t), title="[bold white]Main Menu[/bold white]", subtitle="[bold cyan]★ NDC by SahiDemon ★[/bold cyan]", border_style="cyan", padding=(1, 2)))
        else:
            print(col("  Main Menu\n  1. Download\n  2. Settings\n  3. Exit", "bold"))
        print()
        ch = input("  Choice: ").strip()
        if   ch == "1": run_download(cfg)
        elif ch == "2": settings_menu(cfg)
        elif ch == "3": break

if __name__ == "__main__":
    main()
