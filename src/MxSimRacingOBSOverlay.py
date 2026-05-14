import json
import os
import sys
import re
import io
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, urljoin
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

try:
    import requests
    from bs4 import BeautifulSoup
except Exception:
    requests = None
    BeautifulSoup = None

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None

# Explicit Selenium imports help PyInstaller include the right webdriver modules.
try:
    from selenium import webdriver as selenium_webdriver
    from selenium.webdriver.edge.options import Options as SeleniumEdgeOptions
    from selenium.webdriver.chrome.options import Options as SeleniumChromeOptions
    from selenium.webdriver.edge.webdriver import WebDriver as _EdgeWebDriver
    from selenium.webdriver.chrome.webdriver import WebDriver as _ChromeWebDriver
except Exception:
    selenium_webdriver = None
    SeleniumEdgeOptions = None
    SeleniumChromeOptions = None

APP_NAME = "MxSim Racing OBS Overlay"
APP_VERSION = "2.0.12"
APP_TITLE = f"{APP_NAME} v{APP_VERSION}"
DEFAULT_SCRAPE_INTERVAL_SECONDS = 180
OVERLAY_POLL_SECONDS = 5
SETTINGS_FILE = "mxsim_overlay_settings_v2_0_11.json"
DEFAULT_PLAYER = ""
DEFAULT_URL = "https://mxsimracing.com/league"
DEFAULT_PORT = 3000
BRANDING_HOME_URL = "https://mxsimracing.com/"
BRANDING_REFRESH_SECONDS = 86400

state = {
    "name": DEFAULT_PLAYER,
    "rank": "?",
    "rating": "?",
    "level": "?",
    "races": "?",
    "rank_change": None,
    "avatar_url": "",
    "updated": "-",
    "status": "Waiting for player name...",
    "raw": "",
    "sequence": 0,
}

task_state = {
    "label": "Loading...",
    "detail": "Starting program",
    "progress": 0,
    "is_scraping": False,
}

def set_task(label=None, detail=None, progress=None, is_scraping=None):
    if label is not None:
        task_state["label"] = label
    if detail is not None:
        task_state["detail"] = detail
    if progress is not None:
        task_state["progress"] = max(0, min(100, int(progress)))
    if is_scraping is not None:
        task_state["is_scraping"] = bool(is_scraping)

settings = {
    "player_name": DEFAULT_PLAYER,
    "league_url": DEFAULT_URL,
    "port": DEFAULT_PORT,
    "scrape_interval": DEFAULT_SCRAPE_INTERVAL_SECONDS,
}
last_fetch = 0
server = None
server_thread = None
selenium_driver = None
next_scrape_time = 0
state_lock = threading.RLock()
state_sequence = 0

# Lifecycle and concurrency controls. Only one scrape may run at once.
scrape_lock = threading.Lock()
stop_event = threading.Event()
active_driver_lock = threading.RLock()
active_driver = None
background_thread = None

def update_state(new_values, write_file=True):
    """Update memory and, by default, overlay_data.json.

    Failed scrapes can update the program UI without overwriting the last good OBS overlay.
    """
    global state_sequence
    with state_lock:
        state.update(new_values)
        state_sequence += 1
        state["sequence"] = state_sequence
        snapshot = dict(state)
    if write_file:
        write_overlay_file(snapshot)
    return snapshot

def get_state_snapshot():
    with state_lock:
        snap = dict(state)
        snap["sequence"] = state_sequence
        return snap

def app_dir():
    return os.path.dirname(os.path.abspath(__file__))


def data_dir():
    """Writable per-user data directory. Important for real installs under Program Files."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path

def settings_path():
    return os.path.join(data_dir(), SETTINGS_FILE)

def get_scrape_interval_seconds():
    try:
        value = int(settings.get("scrape_interval", DEFAULT_SCRAPE_INTERVAL_SECONDS))
    except Exception:
        value = DEFAULT_SCRAPE_INTERVAL_SECONDS
    # Safety minimum: keep the app stream-friendly and avoid hammering the website.
    return max(60, value)

def overlay_data_path():
    return os.path.join(data_dir(), "overlay_data.json")

def write_overlay_file(snapshot=None):
    """Write the latest overlay state to disk so localhost and the GUI cannot get out of sync."""
    try:
        data = dict(snapshot if snapshot is not None else get_state_snapshot())
        tmp = overlay_data_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, overlay_data_path())
    except Exception:
        pass

def read_overlay_file():
    """Read the latest overlay state from disk. This is what /api/ranking serves to OBS."""
    try:
        with open(overlay_data_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        snap = get_state_snapshot()
        write_overlay_file(snap)
        return snap

def cleanup_temp_files():
    """Clear temporary files only. Keep user settings and last known overlay data."""
    for path in (overlay_data_path() + ".tmp",):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def branding_cache_dir():
    p = os.path.join(data_dir(), "branding_cache")
    os.makedirs(p, exist_ok=True)
    return p


def branding_paths():
    b = branding_cache_dir()
    return {
        "meta": os.path.join(b, "meta.json"),
        "favicon_png": os.path.join(b, "favicon.png"),
        "header_png": os.path.join(b, "header.png"),
        "window_ico": os.path.join(b, "window.ico"),
    }


def parse_mxsim_branding_urls(html, base=BRANDING_HOME_URL):
    """Resolve favicon + social/header image URLs from mxsimracing.com homepage HTML."""
    fav_url = None
    header_url = None
    if BeautifulSoup and html:
        try:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup.find_all("link"):
                rel = tag.get("rel")
                if not rel:
                    continue
                rel_list = rel if isinstance(rel, (list, tuple)) else [rel]
                rel_join = " ".join(str(r).lower() for r in rel_list)
                if "icon" in rel_join and tag.get("href"):
                    fav_url = urljoin(base, str(tag.get("href")).split("#")[0])
                    break
            og = soup.find("meta", attrs={"property": "og:image"})
            if og and og.get("content"):
                header_url = str(og.get("content")).strip()
        except Exception:
            pass
    if not fav_url:
        fav_url = urljoin(base, "/favicon.png")
    if not header_url:
        header_url = fav_url
    return fav_url, header_url


def _http_get_bytes(url):
    if not requests:
        raise RuntimeError("requests not available")
    headers = {"User-Agent": "Mozilla/5.0 (MxSim Racing OBS Overlay)"}
    r = requests.get(url, headers=headers, timeout=25)
    r.raise_for_status()
    return r.content


def _atomic_write_bytes(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, path)


def refresh_branding_files(force=False):
    """Download favicon + header image from mxsimracing.com into the user cache."""
    paths = branding_paths()
    now = time.time()
    if not force and os.path.isfile(paths["meta"]) and os.path.isfile(paths["favicon_png"]):
        try:
            with open(paths["meta"], "r", encoding="utf-8") as f:
                meta = json.load(f)
            if now - float(meta.get("fetched", 0)) < BRANDING_REFRESH_SECONDS:
                return paths
        except Exception:
            pass
    if not requests:
        return None
    html = requests.get(
        BRANDING_HOME_URL,
        headers={"User-Agent": "Mozilla/5.0 (MxSim Racing OBS Overlay)"},
        timeout=25,
    ).text
    fav_u, head_u = parse_mxsim_branding_urls(html, BRANDING_HOME_URL)
    fav_bytes = _http_get_bytes(fav_u)
    head_bytes = _http_get_bytes(head_u)
    if not Image:
        if fav_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            _atomic_write_bytes(paths["favicon_png"], fav_bytes)
        return paths
    try:
        fav_im = Image.open(io.BytesIO(fav_bytes)).convert("RGBA")
        fav_im.save(paths["favicon_png"], format="PNG")
        head_im = Image.open(io.BytesIO(head_bytes)).convert("RGBA")
        head_im.save(paths["header_png"], format="PNG")
        fav_im.save(
            paths["window_ico"],
            format="ICO",
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        _atomic_write_json(
            paths["meta"],
            {
                "fetched": now,
                "favicon_url": fav_u,
                "header_url": head_u,
            },
        )
    except Exception:
        return load_cached_branding_paths()
    return paths


def load_cached_branding_paths():
    """Return branding paths if cached PNGs exist (even when meta/TTL missing)."""
    paths = branding_paths()
    if os.path.isfile(paths["favicon_png"]):
        return paths
    return None


def apply_branding_to_tk(root, logo_host, paths, bg):
    """Apply cached favicon/header to the Tk chrome (must run on the Tk thread)."""
    if not paths:
        return
    fav = paths.get("favicon_png")
    head = paths.get("header_png")
    ico = paths.get("window_ico")
    if ico and os.path.isfile(ico):
        try:
            root.iconbitmap(ico)
        except Exception:
            pass
    if Image and ImageTk and fav and os.path.isfile(fav):
        try:
            icon_im = Image.open(fav).convert("RGBA")
            icon_im.thumbnail((64, 64), Image.Resampling.LANCZOS)
            root._branding_iconphoto = ImageTk.PhotoImage(icon_im)
            root.iconphoto(True, root._branding_iconphoto)
        except Exception:
            pass
    if Image and ImageTk and head and os.path.isfile(head):
        try:
            hi = Image.open(head).convert("RGBA")
            hi.thumbnail((220, 80), Image.Resampling.LANCZOS)
            root._branding_header_img = ImageTk.PhotoImage(hi)
            for w in logo_host.winfo_children():
                try:
                    w.destroy()
                except Exception:
                    pass
            tk.Label(logo_host, image=root._branding_header_img, bg=bg).pack(anchor="nw")
        except Exception:
            pass


def start_branding_loader(root, logo_host, bg):
    """Background fetch of mxsimracing.com favicon + header; updates UI when ready."""

    def work():
        paths_try = None
        try:
            paths_try = refresh_branding_files(force=False)
        except Exception:
            paths_try = None
        if paths_try is None:
            paths_try = load_cached_branding_paths()
        if paths_try is None:
            try:
                paths_try = refresh_branding_files(force=True)
            except Exception:
                paths_try = load_cached_branding_paths()

        def ui():
            if paths_try:
                apply_branding_to_tk(root, logo_host, paths_try, bg)

        try:
            root.after(0, ui)
        except Exception:
            pass

    threading.Thread(target=work, daemon=True).start()


def load_settings():
    global settings
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            loaded = json.load(f)
        settings.update(loaded)
    except Exception:
        pass

def save_settings():
    with open(settings_path(), "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)

def now_time():
    return time.strftime("%H:%M")

def normalize_text(s):
    return re.sub(r"\s+", " ", s or " ").strip()

def result_is_complete(parsed):
    """A scrape is only successful when the required ranking fields are present.

    Avatar and rank movement are optional. Rank, rating, class/level and races are not.
    This prevents a row that only matched the rider name from being accepted as a good update.
    """
    if not parsed or parsed.get("status") != "OK":
        return False
    required = ("name", "rank", "rating", "level", "races")
    for key in required:
        value = str(parsed.get(key, "")).strip()
        if not value or value == "?" or value == "-":
            return False
    return True

def _clean_candidate_name(candidate, needle):
    candidate = normalize_text(candidate).strip("·•- #")
    # Ranking rows sometimes include a short initials block before the full rider name.
    # If removing it still leaves a name that matches the user's query, use the cleaner version.
    parts = candidate.split()
    if len(parts) >= 3 and len(parts[0]) <= 4 and parts[0].replace('.', '').isupper():
        trimmed = " ".join(parts[1:])
        if query_matches_text(needle, trimmed):
            return trimmed
    return candidate

def query_tokens(query):
    return [t for t in re.split(r"\s+", normalize_text(str(query)).lower()) if len(t) >= 2]

def query_matches_text(query, text):
    q = normalize_text(str(query)).lower().strip()
    t = normalize_text(str(text)).lower()
    if not q:
        return False
    if q in t:
        return True
    toks = query_tokens(q)
    return bool(toks) and all(tok in t for tok in toks)

def parse_player_from_text(text, player_name):
    raw_text = text or ""
    simple = normalize_text(raw_text)
    low = simple.lower()
    needle = normalize_text(player_name).lower()
    if not needle:
        return None
    idx = low.find(needle)
    if idx < 0:
        # Partial/fuzzy search support: find the first location of any query token.
        token_hits = [low.find(tok) for tok in query_tokens(needle) if low.find(tok) >= 0]
        if not token_hits:
            return None
        idx = min(token_hits)

    # League UI often concatenates tokens (e.g. "Amateur III32 races1441") so avoid \b between
    # letters/digits where the site omits spaces. Optional Roman numeral after the tier word.
    levels = r"Rookie|Amateur|Pro|Elite|Legend|Expert|Novice"
    tier = r"\b(" + levels + r")(?:\s*[IVX]{1,4})?"

    # First, parse complete ranking rows from the full rendered page text.
    row_patterns = [
        re.compile(
            r"(?:^|\s)#?\s*(\d{1,5})\s+(.{2,140}?)\s+(?:🔥\s*)?"
            + tier
            + r"\s*(\d+)\s*RACES?\s*(\d{3,5})(?:\s*([+-]\d+))?(?=\s|$|[^\d])",
            re.I,
        ),
        re.compile(
            r"(?:^|\s)#?\s*(\d{1,5})\s+(.{2,140}?)\s+(?:🔥\s*)?"
            + tier
            + r".{0,48}?(\d+)\s*RACES?\s*(\d{3,5})(?:\s*([+-]\d+))?(?=\s|$|[^\d])",
            re.I,
        ),
    ]
    for pattern in row_patterns:
        for m in pattern.finditer(simple):
            candidate = _clean_candidate_name(m.group(2), needle)
            if query_matches_text(needle, candidate):
                chunk = normalize_text(simple[max(0, m.start()-120):min(len(simple), m.end()+120)])
                return {
                    "name": candidate,
                    "rank": m.group(1),
                    "rating": m.group(5),
                    "level": m.group(3).upper(),
                    "races": m.group(4),
                    "rank_change": m.group(6) if m.group(6) else None,
                    "avatar_url": "",
                    "updated": now_time(),
                    "status": "OK",
                    "raw": chunk,
                }

    # Fallback parser around the first matching text occurrence.
    # This is intentionally forgiving but may return incomplete data; callers validate it.
    before = simple[max(0, idx - 260):idx]
    after = simple[idx:idx + 520]
    chunk = normalize_text(before + " " + after)

    numbers_before = re.findall(r"\b\d+\b", before)
    rank = numbers_before[-1] if numbers_before else "?"
    level = "?"
    races = "?"
    rating = "?"
    official_name = normalize_text(player_name)
    rank_change = None

    # Try to parse from the visible context after the matched query token. Do not require
    # the typed query to equal the official website name.
    exact_match = re.search(
        r".{0,180}?"
        + tier
        + r"\s*(\d+)\s*RACES?\s*(\d{3,5})(?:\s*([+-]\d+))?(?=\s|$|[^\d])",
        after,
        re.I,
    )
    if exact_match:
        level = exact_match.group(1).upper()
        races = exact_match.group(2)
        rating = exact_match.group(3)
        rank_change = exact_match.group(4) if exact_match.group(4) else None
    else:
        level_match = re.search(r"\b(" + levels + r")\b", after, re.I)
        if level_match:
            level = level_match.group(1).upper()
        races_match = re.search(r"(\d+)\s*(races|race)", after, re.I)
        if races_match:
            races = races_match.group(1)
            tail = after[races_match.end():races_match.end() + 120]
            rating_match = re.search(r"^\s*(\d{3,5})\b", tail)
            if not rating_match:
                rating_match = re.search(r"(?:^|\D)(\d{3,5})\b", tail)
            if rating_match:
                rating = rating_match.group(1)
        if rating == "?":
            glued = re.search(r"(?:races|race)\s*(\d{3,5})\b", after[:220], re.I)
            if glued:
                rating = glued.group(1)
        if rating == "?":
            candidates = re.findall(r"(?:^|\D)(\d{3,5})(?=\D|$)", after[:220])
            if candidates:
                rating = candidates[-1]

    if rank_change is None and rating != "?":
        rating_pos = after.find(str(rating))
        if rating_pos >= 0:
            movement_tail = after[rating_pos + len(str(rating)): rating_pos + len(str(rating)) + 35]
            movement_match = re.search(r"^\s*([+-]\d+)\b", movement_tail)
            if movement_match:
                rank_change = movement_match.group(1)

    return {
        "name": official_name,
        "rank": rank,
        "rating": rating,
        "level": level,
        "races": races,
        "rank_change": rank_change,
        "avatar_url": "",
        "updated": now_time(),
        "status": "OK",
        "raw": chunk,
    }

def fetch_with_requests(url):
    if requests is None or BeautifulSoup is None:
        return ""
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 OBS Overlay"}, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    return soup.get_text("\n")

def make_browser_options(browser):
    if browser == "edge":
        opts = SeleniumEdgeOptions()
    else:
        opts = SeleniumChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--log-level=3")
    opts.add_argument("--mute-audio")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-background-networking")
    opts.add_argument("--disable-sync")
    opts.add_argument("--disable-dev-shm-usage")
    # Keep image loading enabled so rider profile picture URLs can be read reliably.
    opts.add_argument("--window-size=1200,900")
    try:
        opts.page_load_strategy = "eager"
    except Exception:
        pass
    return opts

def create_selenium_driver():
    if selenium_webdriver is None:
        raise RuntimeError("Selenium is not included in this build. Rebuild with build_exe.bat.")

    last_err = None
    # Try Edge first because it is installed by default on modern Windows.
    for browser in ("edge", "chrome"):
        try:
            opts = make_browser_options(browser)
            if browser == "edge":
                driver = selenium_webdriver.Edge(options=opts)
            else:
                driver = selenium_webdriver.Chrome(options=opts)
            driver.set_page_load_timeout(25)
            return driver
        except Exception as e:
            last_err = e
    raise last_err


def get_best_row_with_avatar(driver, player_name):
    """Return the best visible ranking row/card containing the search text plus avatar URL.

    v2.0.11 fix: do not accept the shortest element that only contains the rider name.
    Walk up the DOM and prefer a parent/card that also contains rank/races/class/rating.
    This keeps avatar extraction optional and prevents incomplete rows from being treated as success.
    """
    try:
        return driver.execute_script(r"""
            const query = String(arguments[0] || '').toLowerCase().trim();
            if(!query) return {text:'', avatar_url:''};
            function norm(s){ return String(s || '').replace(/\s+/g,' ').trim().toLowerCase(); }
            const qTokens = norm(query).split(' ').filter(t => t.length >= 2);
            function matchesQuery(text){
                const t = norm(text);
                if(!t) return false;
                if(t.includes(norm(query))) return true;
                return qTokens.length && qTokens.every(tok => t.includes(tok));
            }
            function visible(el){
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
            }
            function goodUrl(url){
                if(!url) return '';
                url = String(url).trim();
                if(!url || url.startsWith('data:')) return '';
                try { return new URL(url, location.href).href; } catch(e) { return url; }
            }
            function bgUrl(el){
                const bg = window.getComputedStyle(el).backgroundImage || '';
                const m = bg.match(/url\(["']?(.*?)["']?\)/i);
                return m ? goodUrl(m[1]) : '';
            }
            function avatarFrom(root){
                const imgs = Array.from(root.querySelectorAll('img'));
                for(const img of imgs){
                    const src = goodUrl(img.currentSrc || img.src || img.getAttribute('src') || img.getAttribute('data-src'));
                    if(src) return src;
                }
                const nodes = [root, ...Array.from(root.querySelectorAll('*')).slice(0, 160)];
                for(const n of nodes){
                    const u = bgUrl(n);
                    if(u) return u;
                }
                return '';
            }
            function scoreText(text){
                const t = norm(text);
                let score = 0;
                if(matchesQuery(t)) score += 20;
                if(/\b\d{1,5}\b/.test(t)) score += 4;
                if(/\b(rookie|amateur|pro|elite|legend|expert|novice)\b/i.test(t)) score += 12;
                if(/\b\d+\s*races?\b/i.test(t)) score += 12;
                if(/\b\d{3,5}\b/.test(t)) score += 8;
                // Prefer cards/rows, not the entire page.
                if(text.length <= 420) score += 12;
                else if(text.length <= 800) score += 5;
                else if(text.length > 1400) score -= 30;
                return score;
            }
            const baseSelectors = [
                '[class*="rank"]','[class*="standing"]','[class*="leader"]','[class*="rider"]','[class*="player"]',
                'tr','li','article','a','section','div'
            ];
            const elements = Array.from(document.querySelectorAll(baseSelectors.join(','))).filter(visible);
            const candidates = [];
            for(const el of elements){
                const ownText = (el.innerText || el.textContent || '').replace(/\s+/g,' ').trim();
                if(!matchesQuery(ownText)) continue;
                let node = el;
                for(let depth=0; node && depth<8; depth++, node=node.parentElement){
                    if(!visible(node)) continue;
                    const text = (node.innerText || node.textContent || '').replace(/\s+/g,' ').trim();
                    if(!matchesQuery(text) || text.length > 1800) continue;
                    candidates.push({node, text, score: scoreText(text) - depth});
                }
            }
            candidates.sort((a,b) => b.score - a.score || a.text.length - b.text.length);
            if(candidates.length){
                const best = candidates[0];
                return {text: best.text, avatar_url: avatarFrom(best.node), score: best.score};
            }
            return {text:'', avatar_url:''};
        """, player_name) or {"text": "", "avatar_url": ""}
    except Exception:
        return {"text": "", "avatar_url": ""}

def extract_avatar_with_selenium(driver, player_name):
    row = get_best_row_with_avatar(driver, player_name)
    return row.get("avatar_url", "") if isinstance(row, dict) else ""

def click_load_more_if_available(driver):
    """Click the league page's Load More button if it is visible.

    The ranking page initially renders only the first part of the standings.
    Riders below the first page are loaded only after pressing Load More.
    This function is intentionally generic because button markup may change.
    """
    try:
        return bool(driver.execute_script(r"""
            const words = ['load more', 'show more', 'more', 'afficher plus', 'voir plus', 'mehr anzeigen', 'meer tonen'];
            function visible(el){
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && !el.disabled;
            }
            const candidates = Array.from(document.querySelectorAll('button, a, [role=button]'))
                .filter(el => visible(el))
                .filter(el => words.some(w => ((el.innerText || el.textContent || '').trim().toLowerCase()).includes(w)));
            if(candidates.length){
                candidates[0].scrollIntoView({block:'center'});
                candidates[0].click();
                return true;
            }
            window.scrollTo(0, document.body.scrollHeight);
            return false;
        """))
    except Exception:
        return False

def fetch_with_selenium(url, player_name):
    global active_driver
    # Low-lag mode: do not keep a browser alive during gameplay.
    # A temporary headless browser opens only during the scheduled scrape, reads the page,
    # clicks Load More until the rider is visible or the ranking is exhausted, then closes.
    driver = None
    try:
        set_task("Scraping", "Starting browser engine...", 52, True)
        driver = create_selenium_driver()
        with active_driver_lock:
            active_driver = driver
        if stop_event.is_set():
            raise RuntimeError("Application is closing")
        set_task("Scraping", "Loading league page...", 58, True)
        driver.get(url)

        text = ""
        last_len = 0
        max_rounds = 75
        best_row_text = ""
        best_avatar_url = ""

        # Initial render wait.
        end = time.time() + 12
        while time.time() < end:
            try:
                text = driver.execute_script("return document.body ? document.body.innerText : '';" ) or ""
                if len(text) > 500:
                    break
            except Exception:
                pass
            time.sleep(0.5)

        for round_index in range(max_rounds):
            progress = min(86, 62 + int((round_index / max_rounds) * 24))
            set_task("Scraping", f"Searching ranking list... page {round_index + 1}", progress, True)
            try:
                text = driver.execute_script("return document.body ? document.body.innerText : '';" ) or text
                row = get_best_row_with_avatar(driver, player_name)
                avatar_url = row.get("avatar_url", "") if isinstance(row, dict) else ""
                row_text = row.get("text", "") if isinstance(row, dict) else ""
                if row_text:
                    best_row_text = row_text
                    best_avatar_url = avatar_url or best_avatar_url
                    # Stop early only when the row itself already contains complete ranking data.
                    quick = parse_player_from_text(row_text, player_name)
                    if result_is_complete(quick):
                        return {"text": text, "row_text": row_text, "avatar_url": avatar_url}
            except Exception:
                pass

            clicked = click_load_more_if_available(driver)
            if not clicked:
                # Sometimes the button appears only after scrolling. Give the page a short chance.
                time.sleep(0.8)
                try:
                    text_after_scroll = driver.execute_script("return document.body ? document.body.innerText : '';" ) or text
                except Exception:
                    text_after_scroll = text
                clicked = click_load_more_if_available(driver)
                if not clicked and len(text_after_scroll) <= last_len + 25:
                    text = text_after_scroll
                    break
                text = text_after_scroll

            last_len = len(text or "")
            time.sleep(1.0)

        # Final read after all possible Load More clicks.
        try:
            text = driver.execute_script("return document.body ? document.body.innerText : '';" ) or text
        except Exception:
            pass
        row = get_best_row_with_avatar(driver, player_name)
        avatar_url = row.get("avatar_url", "") if isinstance(row, dict) else ""
        row_text = row.get("text", "") if isinstance(row, dict) else ""
        return {"text": text, "row_text": row_text or best_row_text, "avatar_url": avatar_url or best_avatar_url}
    finally:
        if driver is not None:
            set_task("Scraping", "Closing temporary browser...", 88, True)
            try:
                driver.quit()
            except Exception:
                pass
            with active_driver_lock:
                if active_driver is driver:
                    active_driver = None

def fetch_ranking(force=False):
    global last_fetch, state, next_scrape_time

    acquired = scrape_lock.acquire(blocking=False)
    if not acquired:
        set_task("Busy", "Scrape already running. Please wait...", task_state.get("progress", 0), True)
        return read_overlay_file()

    try:
        if stop_event.is_set():
            return read_overlay_file()

        current_overlay = read_overlay_file()
        if not force and time.time() - last_fetch < get_scrape_interval_seconds() and current_overlay.get("status") == "OK":
            return current_overlay

        player = settings["player_name"].strip()
        url = settings["league_url"].strip() or DEFAULT_URL

        if not player:
            set_task("Waiting", "Enter a player name and click Search / scrape", 0, False)
            return update_state({
                "name": "",
                "rank": "?",
                "rating": "?",
                "level": "?",
                "races": "?",
                "rank_change": None,
                "avatar_url": "",
                "updated": now_time(),
                "status": "Waiting for player name...",
                "raw": "Enter a player name as it appears on the league page."
            })

        last_fetch = time.time()
        next_scrape_time = last_fetch + get_scrape_interval_seconds()
        set_task("Scraping", "Starting scrape", 5, True)

        errors = []
        all_text = ""

        try:
            if stop_event.is_set():
                return read_overlay_file()
            set_task("Scraping", "Trying fast HTML scrape...", 15, True)
            html_text = fetch_with_requests(url)
            set_task("Scraping", "Parsing HTML scrape result...", 32, True)
            all_text = html_text
            parsed = parse_player_from_text(html_text, player)
            if result_is_complete(parsed):
                updated_state = update_state(parsed)
                set_task("Ready", "Updated successfully via fast HTML scrape", 100, False)
                return updated_state
            errors.append("HTML scrape: no complete ranking row in static HTML")
        except Exception as e:
            if stop_event.is_set():
                return read_overlay_file()
            errors.append("HTML scrape: " + str(e))

        try:
            if stop_event.is_set():
                return read_overlay_file()
            set_task("Scraping", "Opening temporary headless browser...", 45, True)
            browser_result = fetch_with_selenium(url, player)
            browser_text = browser_result.get("text", "") if isinstance(browser_result, dict) else (browser_result or "")
            row_text = browser_result.get("row_text", "") if isinstance(browser_result, dict) else ""
            avatar_url = browser_result.get("avatar_url", "") if isinstance(browser_result, dict) else ""
            set_task("Scraping", "Parsing browser scrape result...", 90, True)
            all_text = browser_text or all_text
            parsed = None
            if row_text:
                row_parsed = parse_player_from_text(row_text, player)
                if result_is_complete(row_parsed):
                    parsed = row_parsed
            if not result_is_complete(parsed):
                parsed = parse_player_from_text(browser_text, player)
            if result_is_complete(parsed):
                parsed["avatar_url"] = avatar_url or parsed.get("avatar_url", "")
                if row_text:
                    parsed["raw"] = row_text
                updated_state = update_state(parsed)
                set_task("Ready", "Updated successfully via browser scrape", 100, False)
                return updated_state
            errors.append("Browser scrape: no complete ranking row found after render")
        except Exception as e:
            if stop_event.is_set():
                return read_overlay_file()
            errors.append("Browser scrape: " + str(e))

        error_data = {
            "name": player,
            "rank": "?",
            "rating": "?",
            "level": "?",
            "races": "?",
            "rank_change": None,
            "avatar_url": "",
            "updated": now_time(),
            "status": "Player not found: " + player,
            "raw": ("\n".join(errors) + "\n\n--- PAGE TEXT PREVIEW ---\n" + (all_text or "NO TEXT READ"))[:6000],
        }
        set_task("Error", "Player not found or page could not be read. Last good overlay was kept if available.", 100, False)
        previous = read_overlay_file()
        if previous.get("status") == "OK" and previous.get("name"):
            update_state(error_data, write_file=False)
            return previous
        return update_state(error_data, write_file=True)
    finally:
        try:
            scrape_lock.release()
        except RuntimeError:
            pass
        if not stop_event.is_set() and task_state.get("label") == "Scraping":
            set_task("Ready", "Scrape finished", 100, False)

HTML = r'''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Oswald:wght@500;700&display=swap');
* { box-sizing:border-box; }
html, body {
  margin:0;
  padding:0;
  width:100%;
  height:100%;
  background:transparent;
  overflow:hidden;
  font-family:'Oswald','Arial Narrow',Arial,sans-serif;
  color:white;
}
.overlay {
  width:320px;
  height:150px;
  margin:0;
  padding:13px 15px 12px 15px;
  display:flex;
  flex-direction:column;
  justify-content:space-between;
  background:#151515;
  border:1px solid rgba(237,29,47,.95);
  border-radius:7px;
  box-shadow:
    0 0 0 1px rgba(237,29,47,.25),
    0 0 18px rgba(237,29,47,.35),
    0 8px 28px rgba(0,0,0,.40);
  position:relative;
}
.top-row {
  display:flex;
  align-items:center;
  min-width:0;
}
.avatar-wrap {
  width:58px;
  height:58px;
  border-radius:50%;
  display:flex;
  align-items:center;
  justify-content:center;
  margin-right:14px;
  background:radial-gradient(circle at 35% 25%, #444, #171717 70%);
  border:2px solid rgba(255,255,255,.18);
  box-shadow:inset 0 0 0 2px rgba(0,0,0,.35), 0 2px 8px rgba(0,0,0,.35);
  flex:0 0 58px;
}
.avatar {
  width:48px;
  height:48px;
  border-radius:50%;
  display:flex;
  align-items:center;
  justify-content:center;
  color:#fff;
  font-weight:800;
  font-size:17px;
  letter-spacing:.8px;
  background:linear-gradient(135deg,#2d2d2d,#0b0b0b);
  background-size:cover;
  background-position:center;
  border:1px solid rgba(255,255,255,.20);
  overflow:hidden;
}
.info {
  display:flex;
  flex-direction:column;
  justify-content:center;
  min-width:0;
  flex:1;
}
.name {
  font-size:20px;
  line-height:20px;
  font-weight:800;
  letter-spacing:.4px;
  text-transform:uppercase;
  text-shadow:0 2px 8px rgba(0,0,0,.45);
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
}
.sub {
  margin-top:8px;
  font-size:13px;
  line-height:13px;
  display:flex;
  align-items:center;
  gap:7px;
  color:#d9d9d9;
  text-transform:uppercase;
  white-space:nowrap;
}
.fire { color:#ff8b00; font-size:13px; filter:drop-shadow(0 0 4px rgba(255,95,0,.7)); }
.level { color:#f8c24a; font-weight:800; }
.dot { color:#666; font-size:14px; margin-left:1px; margin-right:1px; }
.races { color:#e8e8e8; }
.bottom-row {
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
  width:100%;
}
.rank {
  min-width:58px;
  height:41px;
  display:flex;
  align-items:center;
  justify-content:center;
  font-size:25px;
  color:#b9c2ca;
  letter-spacing:.5px;
  flex:0 0 auto;
}
.rating-pill {
  min-width:82px;
  height:41px;
  border-radius:22px;
  background:#ed1d2f;
  color:#fff;
  display:flex;
  align-items:center;
  justify-content:center;
  font-size:21px;
  font-weight:800;
  letter-spacing:.3px;
  box-shadow:0 8px 16px rgba(237,29,47,.32), inset 0 -2px 0 rgba(0,0,0,.16);
  flex:0 0 auto;
}
.change-badge {
  min-width:62px;
  height:34px;
  border-radius:18px;
  padding:0 10px;
  display:flex;
  visibility:hidden;
  align-items:center;
  justify-content:center;
  font-size:16px;
  font-weight:800;
  letter-spacing:.2px;
  color:#fff;
  background:rgba(255,255,255,.12);
  border:1px solid rgba(255,255,255,.12);
  flex:0 0 auto;
}
.change-badge.up {
  visibility:visible;
  background:rgba(28,180,86,.92);
  box-shadow:0 6px 14px rgba(28,180,86,.25);
}
.change-badge.down {
  visibility:visible;
  background:rgba(240,77,77,.92);
  box-shadow:0 6px 14px rgba(240,77,77,.25);
}
.updated {
  position:absolute;
  right:12px;
  bottom:4px;
  font-family:Arial,sans-serif;
  font-size:10px;
  opacity:0;
}
</style>
</head>
<body>
<div class="overlay" id="overlay">
  <div class="top-row">
    <div class="avatar-wrap"><div class="avatar" id="avatar">--</div></div>
    <div class="info">
      <div class="name" id="name">LOADING...</div>
      <div class="sub">
        <span class="fire">🔥</span>
        <span class="level" id="level">AMATEUR</span>
        <span class="dot">•</span>
        <span class="races"><span id="races">-</span> RACES</span>
      </div>
    </div>
  </div>
  <div class="bottom-row">
    <div class="rank" id="rank">-</div>
    <div class="rating-pill" id="rating">-</div>
    <div class="change-badge" id="rankChange"></div>
  </div>
  <div class="updated" id="updated"></div>
</div>
<script>
function initials(name){
  const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
  if(!parts.length) return '--';
  if(parts.length === 1) return parts[0].slice(0,2).toUpperCase();
  return (parts[0][0] + parts[parts.length-1][0]).toUpperCase();
}
function setAvatar(name, avatarUrl){
  const avatar = document.getElementById('avatar');
  avatar.style.backgroundImage = '';
  avatar.textContent = initials(name);
  if(avatarUrl){
    avatar.style.backgroundImage = `url("${String(avatarUrl).replace(/"/g, '%22')}")`;
    avatar.textContent = '';
  }
}
async function loadRanking(){
  try{
    const res = await fetch('/api/ranking?ts=' + Date.now(), { cache: 'no-store' });
    const data = await res.json();
    if(data.status && data.status !== 'OK') throw new Error(data.status);
    const name = data.name || 'Unknown';
    document.getElementById('name').textContent = name;
    setAvatar(name, data.avatar_url || '');
    document.getElementById('rank').textContent = data.rank && data.rank !== '?' ? data.rank : '-';
    document.getElementById('rating').textContent = data.rating && data.rating !== '?' ? data.rating : '-';
    document.getElementById('level').textContent = data.level && data.level !== '?' ? data.level : '-';
    document.getElementById('races').textContent = data.races && data.races !== '?' ? data.races : '-';
    const changeEl = document.getElementById('rankChange');
    const change = data.rank_change;
    changeEl.className = 'change-badge';
    changeEl.textContent = '';
    if(change && /^[-+]\d+$/.test(String(change))){
      const n = parseInt(change, 10);
      if(n > 0){
        changeEl.textContent = '▲ ' + change;
        changeEl.classList.add('up');
      } else if(n < 0){
        changeEl.textContent = '▼ ' + change;
        changeEl.classList.add('down');
      }
    }
    document.getElementById('updated').textContent = 'Updated ' + (data.updated || '-');
  }catch(e){
    document.getElementById('rank').textContent = '-';
    document.getElementById('name').textContent = 'RANKING UNAVAILABLE';
    setAvatar('Ranking Unavailable', '');
    document.getElementById('level').textContent = 'ERROR';
    document.getElementById('races').textContent = '-';
    document.getElementById('rating').textContent = '-';
    const changeEl = document.getElementById('rankChange');
    changeEl.className = 'change-badge';
    changeEl.textContent = '';
  }
}
loadRanking();
setInterval(loadRanking, 5000);
</script>
</body>
</html>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return
    def _send(self, body, content_type="text/html; charset=utf-8", code=200):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/ranking":
            # Return cached data only. Scraping happens in the background or when the user clicks refresh.
            # This keeps OBS responsive and avoids blocking the browser source during a scrape.
            self._send(json.dumps(read_overlay_file(), ensure_ascii=False, indent=2), "application/json; charset=utf-8")
        elif path == "/raw":
            data = fetch_ranking(force=True)
            self._send("<pre>" + json.dumps(data, ensure_ascii=False, indent=2).replace("<", "&lt;") + "</pre>")
        elif path == "/api/status":
            remaining = max(0, int(next_scrape_time - time.time())) if next_scrape_time else 0
            self._send(json.dumps({"task": task_state, "next_update_seconds": remaining, "version": APP_VERSION, "cache_sequence": state_sequence}, ensure_ascii=False, indent=2), "application/json; charset=utf-8")
        else:
            self._send(HTML)

def start_server(port):
    global server, server_thread
    if server:
        return
    try:
        server = ThreadingHTTPServer(("127.0.0.1", int(port)), Handler)
    except OSError as e:
        raise OSError(f"Port {port} is already in use. Close older versions of the overlay app or choose another port.") from e
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

def background_refresh(update_ui=None):
    global background_thread
    def loop():
        while not stop_event.wait(get_scrape_interval_seconds()):
            try:
                fetch_ranking(force=True)
            except Exception as e:
                set_task("Error", str(e), 100, False)
            if update_ui:
                try: update_ui()
                except Exception: pass
    background_thread = threading.Thread(target=loop, daemon=True)
    background_thread.start()

def main():
    load_settings()
    if not settings.get("league_url"):
        settings["league_url"] = DEFAULT_URL
    if not settings.get("scrape_interval"):
        settings["scrape_interval"] = DEFAULT_SCRAPE_INTERVAL_SECONDS
    update_state({"status": "Waiting for player name...", "updated": now_time()})

    root = tk.Tk()
    root.title(APP_TITLE)
    BG = "#0f1117"
    CARD = "#171a22"
    CARD2 = "#1f2330"
    TEXT = "#f5f7fb"
    MUTED = "#a8afc2"
    RED = "#ed1d2f"
    BORDER = "#2a2f3c"
    root.configure(bg=BG)
    root.geometry("980x740")
    root.minsize(900, 680)

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("TProgressbar", troughcolor="#2b303d", background=RED, bordercolor="#2b303d", lightcolor=RED, darkcolor=RED)
    style.configure("TCombobox", fieldbackground="#11141b", background="#11141b", foreground=TEXT, arrowcolor=TEXT)

    def make_card(parent, title):
        frame = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1, bd=0)
        frame.grid_columnconfigure(0, weight=1)
        title_lbl = tk.Label(frame, text=title, bg=CARD, fg=TEXT, font=("Segoe UI", 12, "bold"))
        title_lbl.grid(row=0, column=0, sticky="w", padx=16, pady=(14, 6))
        return frame

    def make_button(parent, text, command, primary=False):
        return tk.Button(parent, text=text, command=command, bg=(RED if primary else "#e7e7e7"), fg=("white" if primary else "black"), activebackground=("#ff2d40" if primary else "#ffffff"), activeforeground=("white" if primary else "black"), relief="flat", padx=14, pady=8, cursor="hand2")

    # Header — favicon + og:image are downloaded from mxsimracing.com (see branding_cache).
    header = tk.Frame(root, bg=BG)
    header.pack(fill="x", padx=18, pady=(16, 10))
    header.grid_columnconfigure(1, weight=1)
    logo_host = tk.Frame(header, bg=BG)
    logo_host.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 16))
    tk.Label(header, text=APP_NAME, bg=BG, fg=TEXT, font=("Segoe UI", 22, "bold")).grid(row=0, column=1, sticky="w")
    tk.Label(header, text=f"v{APP_VERSION}", bg=BG, fg=MUTED, font=("Segoe UI", 10)).grid(row=0, column=2, sticky="ne", padx=(10, 0))
    subtitle = tk.Label(header, text="Live ranking overlay for OBS using the MxSim Racing league page.", bg=BG, fg=MUTED, font=("Segoe UI", 10), justify="left", wraplength=700)
    subtitle.grid(row=1, column=1, columnspan=2, sticky="w", pady=(2, 0))
    start_branding_loader(root, logo_host, BG)

    content = tk.Frame(root, bg=BG)
    content.pack(fill="both", expand=True, padx=18, pady=0)
    content.grid_columnconfigure(0, weight=3, uniform="cols")
    content.grid_columnconfigure(1, weight=2, uniform="cols")
    content.grid_rowconfigure(1, weight=1)

    # Rider search card
    search_card = make_card(content, "Rider search")
    search_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 12))
    search_card.grid_columnconfigure(0, weight=1)
    info_search = tk.Label(search_card, text="Enter a rider name or partial name. The overlay uses the official name found on the league page.", bg=CARD, fg=MUTED, font=("Segoe UI", 9), wraplength=560, justify="left")
    info_search.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 8))
    row = tk.Frame(search_card, bg=CARD)
    row.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 12))
    row.grid_columnconfigure(0, weight=1)
    name_var = tk.StringVar(value=settings.get("player_name", ""))
    name_entry = tk.Entry(row, textvariable=name_var, font=("Segoe UI", 10), bg="#ffffff", fg="#000000", relief="flat")
    name_entry.grid(row=0, column=0, sticky="ew", ipady=8, padx=(0, 10))
    search_btn_holder = tk.Frame(row, bg=CARD)
    search_btn_holder.grid(row=0, column=1, sticky="e")

    # Matches / status text
    matches_var = tk.StringVar(value="Matches and scrape result will appear here.")
    matches = tk.Label(search_card, textvariable=matches_var, bg="#11141b", fg=TEXT, font=("Consolas", 9), anchor="nw", justify="left", relief="flat", padx=10, pady=8, wraplength=560)
    matches.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 14))

    # Preview card
    preview_card = make_card(content, "Current overlay data")
    preview_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=(0, 12))
    preview_card.grid_columnconfigure(0, weight=1)
    preview_canvas = tk.Canvas(preview_card, width=320, height=150, bg=CARD, highlightthickness=0)
    preview_canvas.grid(row=1, column=0, sticky="n", padx=16, pady=(0, 14))

    # Settings card
    settings_card = make_card(content, "OBS setup and settings")
    settings_card.grid(row=1, column=0, sticky="nsew", padx=(0, 10), pady=(0, 12))
    settings_card.grid_columnconfigure(1, weight=1)

    tk.Label(settings_card, text="OBS URL", bg=CARD, fg=MUTED, font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", padx=16, pady=(2, 6))
    obs_url_var = tk.StringVar(value=f"http://localhost:{settings.get('port', DEFAULT_PORT)}")
    obs_entry = tk.Entry(settings_card, textvariable=obs_url_var, bg="#11141b", fg=TEXT, insertbackground=TEXT, relief="flat")
    obs_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=(2, 6), ipady=5)
    obs_buttons = tk.Frame(settings_card, bg=CARD)
    obs_buttons.grid(row=1, column=2, sticky="e", padx=(8, 16), pady=(2, 6))

    tk.Label(settings_card, text="League URL", bg=CARD, fg=MUTED, font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", padx=16, pady=6)
    url_var = tk.StringVar(value=settings.get("league_url") or DEFAULT_URL)
    url_entry = tk.Entry(settings_card, textvariable=url_var, bg="#11141b", fg=TEXT, insertbackground=TEXT, relief="flat")
    url_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(8, 16), pady=6, ipady=5)

    tk.Label(settings_card, text="Scrape interval", bg=CARD, fg=MUTED, font=("Segoe UI", 9)).grid(row=3, column=0, sticky="w", padx=16, pady=6)
    interval_choices = ["1 minute", "3 minutes", "5 minutes", "10 minutes"]
    sec_to_label = {60:"1 minute", 180:"3 minutes", 300:"5 minutes", 600:"10 minutes"}
    label_to_sec = {v:k for k,v in sec_to_label.items()}
    interval_var = tk.StringVar(value=sec_to_label.get(int(settings.get("scrape_interval", DEFAULT_SCRAPE_INTERVAL_SECONDS)), "3 minutes"))
    interval_box = ttk.Combobox(settings_card, textvariable=interval_var, values=interval_choices, state="readonly", width=14)
    interval_box.grid(row=3, column=1, sticky="w", padx=8, pady=6)

    tk.Label(settings_card, text="Local port", bg=CARD, fg=MUTED, font=("Segoe UI", 9)).grid(row=4, column=0, sticky="w", padx=16, pady=6)
    port_var = tk.StringVar(value=str(settings.get("port", DEFAULT_PORT)))
    port_entry = tk.Entry(settings_card, textvariable=port_var, width=10, bg="#11141b", fg=TEXT, insertbackground=TEXT, relief="flat")
    port_entry.grid(row=4, column=1, sticky="w", padx=8, pady=6, ipady=5)

    help_box = tk.Label(settings_card, text="OBS Browser Source: URL http://localhost:3000 · Width 320 · Height 150 · FPS 10 or 15. Keep this program open while streaming.", bg=CARD, fg=MUTED, font=("Segoe UI", 9), wraplength=600, justify="left")
    help_box.grid(row=5, column=0, columnspan=3, sticky="ew", padx=16, pady=(10, 14))

    # Status card
    status_card = make_card(content, "Status")
    status_card.grid(row=1, column=1, sticky="nsew", padx=(10, 0), pady=(0, 12))
    status_card.grid_columnconfigure(0, weight=1)
    status_var = tk.StringVar(value="Ready")
    countdown_var = tk.StringVar(value="Next update: --:--")
    task_label_var = tk.StringVar(value="Waiting")
    tk.Label(status_card, textvariable=status_var, bg=CARD, fg=TEXT, font=("Segoe UI", 10, "bold"), wraplength=320, justify="left").grid(row=1, column=0, sticky="w", padx=16, pady=(0, 4))
    tk.Label(status_card, textvariable=countdown_var, bg=CARD, fg=MUTED, font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", padx=16, pady=2)
    tk.Label(status_card, textvariable=task_label_var, bg=CARD, fg=MUTED, font=("Segoe UI", 9), wraplength=320, justify="left").grid(row=3, column=0, sticky="w", padx=16, pady=(4, 8))
    progress_var = tk.IntVar(value=0)
    progress = ttk.Progressbar(status_card, orient="horizontal", mode="determinate", maximum=100, variable=progress_var)
    progress.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 12))
    log_text = tk.Text(status_card, height=9, bg="#11141b", fg="#cfd5e6", insertbackground=TEXT, relief="flat", font=("Consolas", 8), wrap="word")
    log_text.grid(row=5, column=0, sticky="nsew", padx=16, pady=(0, 14))
    status_card.grid_rowconfigure(5, weight=1)

    activity_lines = []
    last_task_seen = {"detail": None}

    def add_log(line):
        msg = f"{now_time()} - {line}"
        activity_lines.append(msg)
        del activity_lines[:-60]
        log_text.configure(state="normal")
        log_text.delete("1.0", tk.END)
        log_text.insert(tk.END, "\n".join(activity_lines[-25:]))
        log_text.see(tk.END)
        log_text.configure(state="disabled")

    def draw_preview(data):
        preview_canvas.delete("all")
        preview_canvas.create_rectangle(0, 0, 320, 150, fill="#151515", outline=RED, width=2)
        preview_canvas.create_oval(18, 22, 76, 80, fill="#2c2f36", outline="#555a68", width=2)
        initials = "--"
        nm = data.get("name") or ""
        parts = [p for p in nm.split() if p]
        if len(parts) >= 2:
            initials = (parts[0][0] + parts[-1][0]).upper()
        elif len(parts) == 1:
            initials = parts[0][:2].upper()
        preview_canvas.create_text(47, 51, text=initials, fill="white", font=("Segoe UI", 12, "bold"))
        name = (data.get("name") or "WAITING").upper()
        if len(name) > 22:
            name = name[:21] + "…"
        preview_canvas.create_text(90, 28, text=name, fill="white", anchor="nw", font=("Segoe UI", 14, "bold"))
        sub = f"🔥 {data.get('level') or '-'} · {data.get('races') or '-'} RACES"
        preview_canvas.create_text(90, 56, text=sub, fill="#f3d07b", anchor="nw", font=("Segoe UI", 9, "bold"))
        preview_canvas.create_text(28, 103, text="RANK", fill="#a8afc2", anchor="nw", font=("Segoe UI", 8))
        preview_canvas.create_text(28, 119, text="#" + str(data.get("rank") or "-"), fill="white", anchor="nw", font=("Segoe UI", 14, "bold"))
        preview_canvas.create_text(128, 103, text="RATING", fill="#a8afc2", anchor="nw", font=("Segoe UI", 8))
        preview_canvas.create_text(128, 119, text=str(data.get("rating") or "-"), fill="white", anchor="nw", font=("Segoe UI", 14, "bold"))
        preview_canvas.create_text(224, 103, text="CHANGE", fill="#a8afc2", anchor="nw", font=("Segoe UI", 8))
        ch = data.get("rank_change") or "-"
        preview_canvas.create_text(224, 119, text=str(ch), fill=("#55d683" if str(ch).startswith("+") else "#ff5454" if str(ch).startswith("-") else "white"), anchor="nw", font=("Segoe UI", 14, "bold"))

    def refresh_ui():
        obs_url = f"http://localhost:{settings['port']}"
        obs_url_var.set(obs_url)
        current = read_overlay_file()
        status_var.set(f"{current.get('status', 'Ready')} · Updated {current.get('updated', '-')}")
        remaining = max(0, int(next_scrape_time - time.time())) if next_scrape_time else 0
        countdown_var.set(f"Next automatic scrape in {remaining//60:02d}:{remaining%60:02d}")
        progress_var.set(task_state.get("progress", 0))
        detail = task_state.get("detail", "")
        task_label_var.set(f"{task_state.get('label', 'Ready')}: {detail} ({task_state.get('progress', 0)}%)")
        if detail and detail != last_task_seen.get("detail"):
            add_log(detail)
            last_task_seen["detail"] = detail
        if current.get("status") == "OK":
            matches_var.set(f"Selected rider:\n#{current.get('rank')}  {current.get('name')}  ·  {current.get('level')}  ·  {current.get('rating')}")
        else:
            matches_var.set(str(current.get("status") or "Waiting"))
        draw_preview(current)
        busy = bool(task_state.get("is_scraping"))
        try:
            search_button.configure(state=("disabled" if busy else "normal"))
            refresh_button.configure(state=("disabled" if busy else "normal"))
        except Exception:
            pass
        if not stop_event.is_set():
            root.after(1000, refresh_ui)

    def save_and_refresh():
        global last_fetch, next_scrape_time
        try:
            port = int(port_var.get().strip())
        except Exception:
            messagebox.showerror("Invalid port", "Port must be a number, for example 3000.")
            return
        settings["player_name"] = name_var.get().strip()
        settings["league_url"] = url_var.get().strip() or DEFAULT_URL
        settings["port"] = port
        settings["scrape_interval"] = label_to_sec.get(interval_var.get(), DEFAULT_SCRAPE_INTERVAL_SECONDS)
        save_settings()
        if scrape_lock.locked():
            add_log("Scrape already running; request ignored")
            set_task("Busy", "Scrape already running. Please wait...", task_state.get("progress", 0), True)
            return
        last_fetch = 0
        next_scrape_time = 0
        update_state({
            "name": settings["player_name"],
            "rank": "?",
            "rating": "?",
            "level": "?",
            "races": "?",
            "rank_change": None,
            "avatar_url": "",
            "updated": now_time(),
            "status": "Scrape queued...",
            "raw": "Scrape queued. The OBS overlay will update automatically when the scrape finishes."
        })
        set_task("Loading", "Saved settings. Scrape queued...", 3, True)
        add_log("Manual scrape requested")
        threading.Thread(target=lambda: fetch_ranking(force=True), daemon=True).start()

    def copy_obs_url():
        url = f"http://localhost:{settings['port']}"
        root.clipboard_clear()
        root.clipboard_append(url)
        messagebox.showinfo("Copied", "OBS URL copied:\n" + url)

    search_button = make_button(search_btn_holder, "Search / scrape", save_and_refresh, primary=True)
    search_button.pack(side="left", padx=(0, 8))
    refresh_button = make_button(search_btn_holder, "Refresh now", save_and_refresh)
    refresh_button.pack(side="left")
    make_button(obs_buttons, "Copy URL", copy_obs_url).pack(side="left", padx=(0, 8))
    make_button(obs_buttons, "Open", command=lambda: webbrowser.open(f"http://localhost:{settings['port']}")).pack(side="left")

    # Footer
    footer = tk.Frame(root, bg=BG)
    footer.pack(fill="x", padx=18, pady=(0, 12))
    footer.grid_columnconfigure(0, weight=1)
    credits = tk.Label(footer, text="Developed by Berre Brands & Heimel · Special thanks to MxSim Racing for permission and data access", bg=BG, fg="#747b8c", font=("Segoe UI", 9), wraplength=900, justify="center", anchor="center")
    credits.grid(row=0, column=0, sticky="ew")

    def on_close():
        add_log("Closing application and stopping background services")
        stop_event.set()
        set_task("Closing", "Stopping background services...", 100, False)
        with active_driver_lock:
            drv = active_driver
        if drv is not None:
            try:
                drv.quit()
            except Exception:
                pass
        try:
            if server:
                server.shutdown()
                server.server_close()
        except Exception:
            pass
        cleanup_temp_files()
        try:
            root.destroy()
        except Exception:
            pass

    root.protocol("WM_DELETE_WINDOW", on_close)

    try:
        start_server(settings["port"])
    except Exception as e:
        messagebox.showerror("Server could not start", str(e))
    background_refresh()
    add_log("Program started")
    refresh_ui()
    root.mainloop()

if __name__ == "__main__":
    main()
