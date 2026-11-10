"""Download DETAIL JADWAL & KUNJUNGAN SALES FORCE INDIHOME (bulk) dari Digipos SELA.

Halaman web : /revamp/sales-force-management/jadwal-sales-force/detail/<userId>
Endpoint    :
    daftar SF  : /api/secure/rev/mwa/sf-indihome/schedule/weekly/user            (paginasi)
    assignment : /api/secure/rev/mwa/sf-indihome/schedule/weekly/user/assignment ?userId&assignmentDate&weekStart
    sf_visits  : /api/secure/rev/mwa/reporting-indihome/visit-report/sales-force/visits ?userId&period&page&size

Alur (bulk semua SF dalam 1 minggu):
    1) Ambil SEMUA SF minggu itu dari endpoint weekly/user (sekalian jadi sheet "Ringkasan SF").
    2) Untuk tiap SF, untuk tiap HARI yang punya assignment (totalAssignment > 0), panggil endpoint
       assignment -> daftar ODP + homepass (lat/long, journeyStatus, ringkasan kunjungan).
    3) Ambil detail kunjungan dari sf_visits (alasan gagal, waktu check-in, durasi, jarak, dll.)
       dan kawinkan dengan detail homepass.
    4) Tulis 2 sheet: "Ringkasan SF" (1 baris/SF) + "Detail Homepass" (1 baris/homepass).

CARA PAKAI:
    MODE OTOMATIS (disarankan — tanpa copy curl / snippet manual):
        python -m utils.sela_scraper --auto
        -> Playwright buka Chrome (profil tersimpan di storage/sela/data/browser_profile).
           Login manual sekali (SSO + CAPTCHA). Script ambil sendiri KUNCI AES + header
           (Authorization/x-dgp-nonce/Cookie). Saat token/nonce basi, header DIREFRESH OTOMATIS.
        -> Isi rentang tanggal (atau env DIGIPOS_SF_FROM / DIGIPOS_SF_TO). Tambahkan --headless
           kalau sesi login masih tersimpan.

    MODE MANUAL:
        python -m utils.sela_scraper
        -> Paste kunci AES + curl dari halaman detail SF IndiHome.
"""
import argparse
import base64
import datetime
import json
import os
import re
import sys
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import openpyxl
import requests
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import load_der_private_key, load_der_public_key

# ==========================================
# DIREKTORI & KONFIGURASI SELA
# ==========================================
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELA_ROOT = os.environ.get("DIGIPOS_SELA_ROOT") or os.path.join(PROJECT_ROOT, "storage", "sela")

CONFIG_DIR = os.path.join(SELA_ROOT, "config")
CRED_FILE = os.path.join(CONFIG_DIR, "digipos_sf_indihome.json")
PROFILE_DIR = os.path.join(SELA_ROOT, "data", "browser_profile")
SESSION_FILE = os.path.join(PROFILE_DIR, "session_cookies.json")
CACHE_ROOT = os.path.join(SELA_ROOT, "data", "cache_detail_sf")
VISITS_CACHE_ROOT = os.path.join(SELA_ROOT, "data", "cache_sf_visits")
ARCHIVE_DIR = os.path.join(SELA_ROOT, "data", "results")
_DAY_DIR = os.path.join(ARCHIVE_DIR, datetime.date.today().isoformat())
OUTPUT_DIR = os.environ.get("RUNPAGI_OUTPUT_DIR") or os.path.join(_DAY_DIR, "upload_generator")

JADWAL_URL = "https://digipos.telkomsel.com/revamp/sales-force-management/jadwal-sales-force"
SF_REFERER = JADWAL_URL
BASE_SCHEDULE = "https://digipos.telkomsel.com/api/secure/rev/mwa/sf-indihome/schedule"

REQUEST_TIMEOUT = 120
MAX_PAGES = 1000
REQUEST_DELAY = float(os.environ.get("DIGIPOS_SF_DELAY", "0.6"))
RATE_LIMIT_RETRIES = 6
RATE_LIMIT_BACKOFF = 5.0
SIZE_OVERRIDE = os.environ.get("DIGIPOS_SF_SIZE", "100").strip()
WEEKLY_CACHE_TTL_HOURS = float(os.environ.get("DIGIPOS_SF_LIST_TTL", "12"))
FETCH_VISITS = os.environ.get("DIGIPOS_SF_FETCH_VISITS", "1").strip().lower() not in ("0", "false", "no")

REPLAY_HEADERS = [
    "authorization", "cookie", "x-dgp-nonce", "referer", "baggage",
    "sentry-trace", "user-agent", "accept", "accept-language"
]
HARI_ID = {0: "Senin", 1: "Selasa", 2: "Rabu", 3: "Kamis", 4: "Jumat", 5: "Sabtu", 6: "Minggu"}

HOMEPASS_COLS = [
    "User ID", "Nama SF", "Kode", "Tanggal", "Hari", "ODP", "Homepass",
    "Latitude", "Longitude", "Urutan", "Journey Status", "Journey Desc",
    "Hasil Kunjungan", "Catatan Kunjungan", "Kode Hasil", "Waktu Check-In",
    "Durasi Kunjungan (detik)", "Jarak Check-In (meter)", "Journey ID",
    "Total Kunjungan", "Kunjungan Terakhir"
]


# ==========================================
# SESSION & CURL PARSER HELPER
# ==========================================
def create_session():
    """Session HTTP generik dengan keep-alive."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "id-ID",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Priority": "u=0",
    })
    return session


def parse_curl_cmd(raw_text):
    """Parse perintah 'Copy as cURL' dari DevTools (mendukung format cmd Windows & bash/ps)."""
    text = raw_text.strip()
    if not text:
        return None, None

    text = re.sub(r'\^\s*\r?\n\s*', ' ', text)
    text = re.sub(r'\\\s*\r?\n\s*', ' ', text)

    def unescape_cmd(s):
        return re.sub(r'\^(.)', r'\1', s)

    is_cmd_style = '^"' in text
    if is_cmd_style:
        m_url = re.search(r'curl(?:\.exe)?\s+\^"(.*?)\^"', text)
        header_iter = re.finditer(r'-H\s+\^"(.*?)\^"', text)
        cookie_iter = re.finditer(r'(?:-b|--cookie)\s+\^"(.*?)\^"', text)
        unescape = unescape_cmd
    else:
        m_url = re.search(r'''curl(?:\.exe)?\s+['"](.*?)['"]''', text)
        header_iter = re.finditer(r'''-H\s+['"](.*?)['"]''', text)
        cookie_iter = re.finditer(r'''(?:-b|--cookie)\s+['"](.*?)['"]''', text)
        unescape = lambda s: s

    url = unescape(m_url.group(1)) if m_url else None
    headers = {}
    for m in header_iter:
        line = unescape(m.group(1))
        if ':' in line:
            name, _, value = line.partition(':')
            headers[name.strip()] = value.strip()

    for m in cookie_iter:
        cookie_val = unescape(m.group(1))
        cookie_val = re.sub(r';\s*Path=/\s*$', '', cookie_val)
        headers['Cookie'] = cookie_val

    return url, headers


def header_get(headers, name):
    """Ambil value header secara case-insensitive."""
    if not headers:
        return None
    name_lower = name.lower()
    for k, v in headers.items():
        if k.lower() == name_lower:
            return v
    return None


def prompt_paste_curl(label):
    """Minta user paste curl (multi-baris) di terminal, diakhiri 1 baris kosong."""
    print(f"\n>>> Paste curl untuk {label} di bawah ini (Copy as cURL dari DevTools),")
    print(">>> lalu tekan Enter sekali lagi di baris kosong untuk lanjut:\n")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "" and lines:
            break
        if line.strip() != "":
            lines.append(line)
    return "\n".join(lines)


def replay_headers(curl_headers):
    out = {}
    canon_map = {
        "authorization": "Authorization",
        "cookie": "Cookie",
        "x-dgp-nonce": "x-dgp-nonce",
        "referer": "Referer",
        "baggage": "baggage",
        "sentry-trace": "sentry-trace",
        "user-agent": "User-Agent",
        "accept": "Accept",
        "accept-language": "Accept-Language",
    }
    for name in REPLAY_HEADERS:
        v = header_get(curl_headers, name)
        if v:
            out[canon_map[name]] = v
    out.setdefault("Referer", SF_REFERER)
    return out


def extract_endpoint_url(raw, parsed_url):
    needle = "sf-indihome/schedule/weekly/user"
    if parsed_url and needle in parsed_url:
        return parsed_url
    text = re.sub(r'\^\s*\r?\n\s*', ' ', raw)
    text = re.sub(r'\\\s*\r?\n\s*', ' ', text)
    for m in re.finditer(r'\^"(.*?)\^"', text):
        cand = re.sub(r'\^(.)', r'\1', m.group(1))
        if cand.startswith("http") and needle in cand:
            return cand
    for m in re.finditer(r'''['"](https?://[^'"]*?)['"]''', text):
        if needle in m.group(1):
            return m.group(1)
    return parsed_url


# ==========================================
# KRIPTOGRAFI AES-256-GCM & KUNCI SESI
# ==========================================
def derive_key_from_storage(servpub_b64, priv_b64):
    """Kunci AES-256 = koordinat-X ECDH P-256 (serverPublicKey, clientPrivateKey)."""
    pub = load_der_public_key(base64.b64decode(servpub_b64))
    priv = load_der_private_key(base64.b64decode(priv_b64), password=None)
    return priv.exchange(ec.ECDH(), pub)


def decrypt_response(enc, key):
    """Decrypt body 'IV:CIPHERTEXT:TAG' (hex) -> plaintext str. key = 32 byte."""
    parts = enc.strip().split(":")
    if len(parts) != 3:
        raise ValueError("Format response bukan IV:CIPHERTEXT:TAG (kemungkinan belum/tidak terenkripsi)")
    iv, ct, tag = (bytes.fromhex(p) for p in parts)
    return AESGCM(key).decrypt(iv, ct + tag, None).decode("utf-8")


def _looks_encrypted(body):
    return bool(re.fullmatch(r"[0-9a-fA-F]+:[0-9a-fA-F]+:[0-9a-fA-F]+", body.strip()))


def load_aes_key():
    env = os.environ.get("DIGIPOS_SF_AES_KEY", "").strip()
    if env:
        return env
    try:
        if os.path.exists(CRED_FILE):
            with open(CRED_FILE, "r", encoding="utf-8") as f:
                return (json.load(f).get("aes_key_hex") or "").strip()
    except Exception as e:
        print(f"  [!] Gagal baca {os.path.basename(CRED_FILE)}: {e}")
    return ""


def save_aes_key(key_hex):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    data = {"aes_key_hex": key_hex, "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    with open(CRED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"  [OK] Kunci AES disimpan ke: {os.path.basename(CRED_FILE)}")


def valid_key_hex(s):
    s = (s or "").strip()
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", s))


def obtain_aes_key():
    key = load_aes_key()
    while not valid_key_hex(key):
        if key:
            print("  [!] Kunci tidak valid (harus 64 karakter hex).")
        print("\n>>> Paste KUNCI AES SESI (hex 64 char) dari snippet Console,")
        print(">>> atau tekan Enter kosong untuk batal:")
        key = input("    Kunci: ").strip()
        if not key:
            return None
    save_aes_key(key)
    return key


# ==========================================
# PLAYWRIGHT BROWSER AUTH (KHUSUS SELA REVAMP)
# ==========================================
AES_KEY_SNIPPET = r"""
async () => {
  const A = performance.getEntriesByType('resource').map(e => e.name)
    .filter(n => n.includes('/share-module/assets/') && n.endsWith('.js'));
  const su = A.find(n => /\/Storage-[^/]+\.js$/.test(n));
  if (!su) return null;
  let cu = null;
  for (const u of A.filter(n => /\/index-[^/]+\.js$/.test(n))) {
    try { if ((await fetch(u).then(r => r.text())).includes('AES key must be 32 bytes')) { cu = u; break; } } catch (e) {}
  }
  if (!cu) return null;
  const S = await import(su), I = await import(cu);
  const st = Object.values(S).find(v => v && typeof v.getItem === 'function');
  if (!st) return null;
  const sp = await st.getItem('SERVPUBKEY'), pv = await st.getItem('QKWEJRHJKQ');
  if (!sp || !pv) return null;
  const hx = x => atob(x).split('').map(c => c.charCodeAt(0).toString(16).padStart(2, '0')).join('');
  return await I.g('p-256', hx(sp), hx(pv));
}
"""


def _save_browser_session(context):
    try:
        os.makedirs(PROFILE_DIR, exist_ok=True)
        cookies = [c for c in context.cookies() if "telkomsel.com" in c.get("domain", "")]
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f)
    except Exception as e:
        print(f"  [i] Gagal menyimpan cookie sesi: {str(e)[:80]}")


def _restore_browser_session(context):
    try:
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            if cookies:
                context.add_cookies(cookies)
                print(f"  [i] {len(cookies)} cookie sesi dipulihkan dari run sebelumnya.")
    except Exception as e:
        print(f"  [i] Gagal memulihkan cookie sesi: {str(e)[:80]}")


def _launch_browser_context(pw, headless):
    os.makedirs(PROFILE_DIR, exist_ok=True)
    kwargs = dict(user_data_dir=PROFILE_DIR, headless=headless)
    if headless:
        kwargs["viewport"] = {"width": 1280, "height": 850}
    else:
        kwargs.update(no_viewport=True, args=["--start-maximized"])
    try:
        ctx = pw.chromium.launch_persistent_context(channel="chrome", **kwargs)
    except Exception as e:
        print(f"  [i] Chrome tidak bisa dipakai ({str(e).splitlines()[0][:80]}), pakai Chromium bawaan.")
        ctx = pw.chromium.launch_persistent_context(**kwargs)
    _restore_browser_session(ctx)
    return ctx


class SfAuth:
    """Sesi browser login untuk scraping SF IndiHome SELA revamp."""

    def __init__(self, headless=False):
        self.headless = headless
        self._pw = None
        self.context = None
        self.page = None

    def open(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.context = _launch_browser_context(self._pw, self.headless)
        self.page = self.context.new_page()
        return self

    def try_key(self):
        """Coba ambil kunci AES sekarang. Return hex 64 char atau None."""
        try:
            k = self.page.evaluate(AES_KEY_SNIPPET)
            return k if (isinstance(k, str) and len(k) == 64) else None
        except Exception:
            return None

    def ensure_ready(self, wait_seconds=600):
        """Buka halaman jadwal SF, tunggu sampai login SSO + modul siap (kunci AES bisa diambil)."""
        page = self.page
        print(f"  Membuka {JADWAL_URL} ...")
        print("  Alur login: DigiPOS -> SSO (email Microsoft) -> user+pass SSO Telkomsel -> verify -> masuk.")
        print("  Lakukan semua langkah login di jendela browser; saya tunggu sampai selesai (maks "
              f"{wait_seconds // 60} menit).")
        try:
            page.goto(JADWAL_URL, wait_until="domcontentloaded")
        except Exception as e:
            print(f"  [!] gagal membuka halaman: {str(e)[:80]}")
        told_login = told_sso = False
        logged_in_since = None
        last_goto = 0.0
        t0 = time.time()
        while time.time() - t0 < wait_seconds:
            key = self.try_key()
            if key:
                print("  [OK] Login terdeteksi & kunci AES diambil otomatis.")
                return key
            url = page.url or ""
            host = (urlsplit(url).netloc or "").lower()
            path = (urlsplit(url).path or "").lower()
            on_digipos = host == "digipos.telkomsel.com"
            if not on_digipos:
                if not told_sso:
                    print("  [i] Di halaman SSO/Microsoft/verify — lanjutkan login di browser, saya tunggu...")
                    told_sso = True
                logged_in_since = None
            elif path.endswith("/revamp/login"):
                if not told_login:
                    print("  [!] Di halaman login DigiPOS. Klik login (SSO) dan selesaikan sampai verify.")
                    told_login = True
                logged_in_since = None
            elif path.endswith("/revamp/callback"):
                logged_in_since = None
            else:
                if logged_in_since is None:
                    logged_in_since = time.time()
                if not url.lower().startswith(JADWAL_URL.lower()) \
                        and time.time() - logged_in_since > 6 and time.time() - last_goto > 10:
                    last_goto = time.time()
                    try:
                        page.goto(JADWAL_URL, wait_until="domcontentloaded")
                    except Exception:
                        pass
            page.wait_for_timeout(1500)
        print("  [GAGAL] Timeout menunggu login / kunci AES.")
        return None

    def capture_headers(self, timeout_seconds=60):
        """Reload halaman jadwal, tangkap header dari request sf-indihome/schedule."""
        page, seen = self.page, []
        on_req = lambda r: seen.append(r) if "sf-indihome/schedule" in r.url else None
        page.on("request", on_req)
        try:
            try:
                page.goto(JADWAL_URL, wait_until="domcontentloaded")
            except Exception:
                pass
            t0 = time.time()
            while time.time() - t0 < timeout_seconds:
                for r in reversed(seen):
                    try:
                        h = r.all_headers()
                    except Exception:
                        continue
                    if h.get("authorization", "").lower().startswith("bearer ") and h.get("x-dgp-nonce"):
                        return replay_headers(h)
                page.wait_for_timeout(500)
            return None
        finally:
            page.remove_listener("request", on_req)

    def get_token_for_menu(self, menu_id):
        """Generate token + nonce untuk MENU_ID tertentu (mis. REV-DGP-PELAPORAN-VISIT-REPORT)."""
        try:
            return self.page.evaluate(r'''async (menu_id) => {
                const A = performance.getEntriesByType('resource').map(e => e.name)
                  .filter(n => n.includes('/share-module/assets/') && n.endsWith('.js'));
                const su = A.find(n => /\/Storage-[^/]+\.js$/.test(n));
                const uu = A.find(n => /\/Utils-[^/]+\.js$/.test(n));
                if (!su || !uu) return null;
                const S = await import(su);
                const U = await import(uu);
                const st = Object.values(S).find(v => v && typeof v.getItem === 'function');
                if (!st || !U.getAuthToken) return null;
                if (menu_id) {
                    await st.setItem('MENU_ID', menu_id);
                }
                return await U.getAuthToken();
            }''', menu_id)
        except Exception:
            return None

    def close(self):
        try:
            if self.context:
                _save_browser_session(self.context)
                self.context.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass


# ==========================================
# HTTP REQUEST & PAGINASI SF
# ==========================================
def set_query_param(url, key, value):
    parts = urlsplit(url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q[key] = str(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))


def get_decrypted(session, url, headers, key, what="halaman"):
    """GET URL, decrypt AES-256-GCM, return (parsed_json, error_str) dengan retry otomatis untuk 429/5xx."""
    backoff = RATE_LIMIT_BACKOFF
    for attempt in range(1, RATE_LIMIT_RETRIES + 1):
        try:
            r = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        except Exception as e:
            if attempt < RATE_LIMIT_RETRIES:
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            return None, f"network error: {e}"
        if r.status_code == 429 or 500 <= r.status_code < 600:
            if attempt < RATE_LIMIT_RETRIES:
                ra = r.headers.get("Retry-After")
                wait = float(ra) if (ra and ra.replace('.', '', 1).isdigit()) else backoff
                print(f"    [i] HTTP {r.status_code} ({what}), tunggu {wait:.0f}s lalu coba lagi "
                      f"(percobaan {attempt}/{RATE_LIMIT_RETRIES - 1})...")
                time.sleep(wait)
                backoff = min(backoff * 2, 60)
                continue
            return None, f"HTTP {r.status_code} (menyerah setelah {RATE_LIMIT_RETRIES} percobaan): {r.text[:160]}"
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {r.text[:160]}"
        body = r.text
        if not _looks_encrypted(body):
            return None, f"response tidak terenkripsi (nonce/token ditolak?): {body[:160]}"
        try:
            plain = decrypt_response(body, key)
        except Exception as e:
            return None, f"gagal decrypt: {e}"
        try:
            return json.loads(plain), None
        except Exception as e:
            return None, f"gagal parse JSON: {e} :: {plain[:160]}"
    return None, "gagal (retry habis)"


def fetch_page(session, url, headers, key, page):
    return get_decrypted(session, set_query_param(url, "page", page), headers, key, what=f"halaman {page}")


def fetch_all_users(session, url, headers, key, week_start=None, on_progress=None):
    """Ambil semua user dari endpoint weekly/user untuk 1 minggu (paginasi otomatis)."""
    if week_start:
        url = set_query_param(url, "weekStart", week_start)
    if SIZE_OVERRIDE:
        url = set_query_param(url, "size", SIZE_OVERRIDE)
    first, err = fetch_page(session, url, headers, key, 0)
    if err:
        return [], f"halaman 0: {err}"
    data = first.get("data") or {}
    paging = data.get("pagingResponse") or {}
    total_pages = int(paging.get("totalPages") or 1)
    users = list(data.get("users") or [])
    if on_progress:
        on_progress(1, total_pages, len(users))
    page = 1
    while page < min(total_pages, MAX_PAGES):
        j, err = fetch_page(session, url, headers, key, page)
        if err:
            return users, f"halaman {page}: {err}"
        users.extend((j.get("data") or {}).get("users") or [])
        if on_progress:
            on_progress(page + 1, total_pages, len(users))
        page += 1
        time.sleep(REQUEST_DELAY)
    return users, None


def _fmt_date_header(date_str):
    try:
        d = datetime.date.fromisoformat(date_str[:10])
        return f"{HARI_ID.get(d.weekday(), '')} {d.strftime('%d-%m')}".strip()
    except Exception:
        return date_str


def flatten_users(users):
    """Return (rows, day_headers) untuk Sheet 1 Ringkasan SF."""
    day_order = []
    for u in users:
        for a in (u.get("assignments") or []):
            d = a.get("date")
            if d and d not in day_order:
                day_order.append(d)
    day_headers = [_fmt_date_header(d) for d in day_order]

    rows = []
    for u in users:
        ms = u.get("monthlySummary") or {}
        ws = u.get("weeklySummary") or {}
        amap = {a.get("date"): a for a in (u.get("assignments") or [])}
        row = {
            "Nama SF": u.get("name"),
            "Kode": u.get("code"),
            "User ID": u.get("userId"),
            "Status Karyawan": u.get("employmentTypeDesc") or u.get("employmentType"),
            "Nomor HP": u.get("contactNumber"),
            "Target Visit (Bulan)": ms.get("targetVisit"),
            "Target PS (Bulan)": ms.get("targetPs"),
            "Target Mingguan": ws.get("referenceTarget"),
            "Total Assignment (Minggu)": ws.get("totalAssignment"),
            "Kekurangan": ws.get("remainder"),
            "Status Rute": ws.get("status"),
        }
        for d, h in zip(day_order, day_headers):
            a = amap.get(d) or {}
            tot = a.get("totalAssignment")
            st = a.get("status")
            row[h] = tot if st in (None, "") else f"{tot} ({st})"
        rows.append(row)
    return rows, day_headers


# ==========================================
# ENDPOINT URL & CACHE HELPER
# ==========================================
def base_schedule_url(curl_url):
    p = urlsplit(curl_url)
    return f"{p.scheme}://{p.netloc}/api/secure/rev/mwa/sf-indihome/schedule"


def reporting_base_url(curl_url_or_base):
    p = urlsplit(curl_url_or_base)
    return f"{p.scheme}://{p.netloc}/api/secure/rev/mwa/reporting-indihome/visit-report/sales-force"


def weekly_url(base):
    return f"{base}/weekly/user?sortOrder=asc&sortBy=REMAINDER"


def assignment_url(base, user_id, date, week_start):
    q = urlencode({"userId": user_id, "assignmentDate": date, "weekStart": week_start})
    return f"{base}/weekly/user/assignment?{q}"


def get_week_start(url):
    return dict(parse_qsl(urlsplit(url).query, keep_blank_values=True)).get("weekStart")


def is_past_week(week_start_str):
    try:
        ws = datetime.date.fromisoformat(str(week_start_str)[:10])
        today = datetime.date.today()
        current_monday = today - datetime.timedelta(days=today.weekday())
        return ws < current_monday
    except Exception:
        return False


def is_past_period(period_str):
    try:
        current_period = datetime.date.today().strftime("%Y%m")
        return str(period_str) < current_period
    except Exception:
        return False


def cache_path(week_start, user_id, date):
    d = os.path.join(CACHE_ROOT, week_start)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{user_id}_{date}.json")


def load_cache(week_start, user_id, date):
    p = cache_path(week_start, user_id, date)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def save_cache(week_start, user_id, date, data):
    try:
        with open(cache_path(week_start, user_id, date), "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"    [!] gagal simpan cache {user_id}_{date}: {e}")


def weekly_cache_path(week_start):
    d = os.path.join(CACHE_ROOT, week_start)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "_weekly_users.json")


def load_weekly_cache(week_start):
    if os.environ.get("DIGIPOS_SF_REFRESH_LIST", "").strip() in ("1", "true", "yes"):
        return None
    p = weekly_cache_path(week_start)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if not is_past_week(week_start):
            saved = datetime.datetime.fromisoformat(obj["saved_at"])
            age_h = (datetime.datetime.now() - saved).total_seconds() / 3600.0
            if age_h > WEEKLY_CACHE_TTL_HOURS:
                return None
        return obj.get("users") or []
    except Exception:
        return None


def save_weekly_cache(week_start, users):
    try:
        with open(weekly_cache_path(week_start), "w", encoding="utf-8") as f:
            json.dump({"saved_at": datetime.datetime.now().isoformat(), "users": users}, f)
    except Exception as e:
        print(f"    [!] gagal simpan cache daftar mingguan: {e}")


def visits_cache_path(period, user_id):
    d = os.path.join(VISITS_CACHE_ROOT, str(period))
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{user_id}.json")


def load_visits_cache(period, user_id):
    if os.environ.get("DIGIPOS_SF_REFRESH_VISITS", "").strip() in ("1", "true", "yes"):
        return None
    p = visits_cache_path(period, user_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if not is_past_period(period):
            saved = datetime.datetime.fromisoformat(obj.get("saved_at", "2000-01-01"))
            age_h = (datetime.datetime.now() - saved).total_seconds() / 3600.0
            if age_h > WEEKLY_CACHE_TTL_HOURS:
                return None
        return obj.get("visits") or []
    except Exception:
        return None


def save_visits_cache(period, user_id, visits):
    try:
        with open(visits_cache_path(period, user_id), "w", encoding="utf-8") as f:
            json.dump({"saved_at": datetime.datetime.now().isoformat(), "visits": visits}, f)
    except Exception as e:
        print(f"    [!] gagal simpan cache visits {period}_{user_id}: {e}")


def fetch_sf_visits(session, reporting_base, reporting_headers, key, user_id, period, reauth_fn):
    """Ambil riwayat kunjungan SF dari visit-report/sales-force/visits (bulk per bulan)."""
    global FETCH_VISITS
    if not FETCH_VISITS or not reporting_headers:
        return [], key
    cached = load_visits_cache(period, user_id)
    if cached is not None:
        return cached, key

    all_visits = []
    page = 0
    try:
        size = int(os.environ.get("DIGIPOS_SF_SIZE", "100"))
    except (ValueError, TypeError):
        size = 100
    ferr = None
    while True:
        q = urlencode({"userId": user_id, "period": period, "page": page, "size": size})
        url = f"{reporting_base}/visits?{q}"
        j, ferr = get_decrypted(session, url, reporting_headers, key, what=f"visits {user_id}/{period}/p{page}")
        if ferr:
            if _is_auth_error(ferr) or _is_key_error(ferr):
                print(f"  [!] Otorisasi sf_visits kedaluwarsa/tidak diizinkan ({ferr}).")
                ok, key = reauth_fn(reporting_headers, key, menu_id="REV-DGP-PELAPORAN-VISIT-REPORT") if reauth_fn else (False, key)
                if ok:
                    continue
                else:
                    print("  [!] Otorisasi sf_visits tidak tersedia. sf_visits dinonaktifkan untuk sisa proses.")
                    FETCH_VISITS = False
                    return [], key
            print(f"    [!] Visits {user_id} {period} p{page} gagal ({ferr}). Dilewati.")
            break
        data = (j.get("data") or {})
        visits = data.get("visits") or []
        all_visits.extend(visits)
        paging = data.get("pagingResponse") or {}
        if not paging.get("hasNext"):
            break
        page += 1
        time.sleep(REQUEST_DELAY)

    if not ferr:
        save_visits_cache(period, user_id, all_visits)
    return all_visits, key


# ==========================================
# PARSING HOMEPASS & EXCEL WRITER
# ==========================================
def _hari(date_str):
    try:
        return HARI_ID.get(datetime.date.fromisoformat(date_str[:10]).weekday(), "")
    except Exception:
        return ""


def assignment_rows(user, date, assign_data, visit_map=None):
    rows = []
    visit_map = visit_map or {}
    for odp in (assign_data.get("listOdp") or []):
        odp_name = odp.get("odpName")
        for hp in (odp.get("homepass") or []):
            vs = hp.get("visitSummary") or {}
            hp_id = str(hp.get("homepass") or "")
            v = visit_map.get((hp_id, date)) or visit_map.get(hp_id) or {}
            res_obj = v.get("result") or {}
            res_label = res_obj.get("label") or ""
            note = res_obj.get("note") or ""

            if not note and "(" in res_label and res_label.endswith(")"):
                m = re.match(r"^(.*?)\s*\((.*)\)$", res_label)
                if m:
                    res_label = m.group(1).strip()
                    note = m.group(2).strip()

            rows.append({
                "User ID": user.get("userId"),
                "Nama SF": user.get("name"),
                "Kode": user.get("code"),
                "Tanggal": date,
                "Hari": _hari(date),
                "ODP": odp_name,
                "Homepass": hp.get("homepass"),
                "Latitude": hp.get("latitude"),
                "Longitude": hp.get("longitude"),
                "Urutan": hp.get("orderSchedule"),
                "Journey Status": hp.get("journeyStatus"),
                "Journey Desc": hp.get("journeyDesc"),
                "Hasil Kunjungan": res_label,
                "Catatan Kunjungan": note,
                "Kode Hasil": res_obj.get("code") or "",
                "Waktu Check-In": v.get("checkInAt") or "",
                "Durasi Kunjungan (detik)": v.get("durationSeconds") if v.get("durationSeconds") is not None else "",
                "Jarak Check-In (meter)": v.get("checkInDistanceMeters") if v.get("checkInDistanceMeters") is not None else "",
                "Journey ID": v.get("journeyId") or "",
                "Total Kunjungan": vs.get("totalVisit"),
                "Kunjungan Terakhir": vs.get("lastVisitDate"),
            })
    return rows


def _safe_save(wb, out):
    for _ in range(2):
        try:
            wb.save(out)
            return out
        except PermissionError:
            alt = f"{out[:-5]}_{datetime.datetime.now():%H%M%S}.xlsx"
            try:
                wb.save(alt)
                print(f"  [!] '{os.path.basename(out)}' sedang TERBUKA di Excel — disimpan sebagai "
                      f"'{os.path.basename(alt)}'. Tutup file lama lalu rename kalau mau.")
                return alt
            except PermissionError:
                print("  [!] Gagal simpan (file terkunci). Tutup Excel, tekan Enter untuk coba lagi...")
                try:
                    input()
                except EOFError:
                    raise
    wb.save(out)
    return out


def write_workbook(users, homepass_rows, week_start):
    out = os.path.join(OUTPUT_DIR, f"detail-sf-indihome_{week_start}.xlsx")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    wb = openpyxl.Workbook()

    ws1 = wb.active
    ws1.title = "Ringkasan SF"
    rows, day_headers = flatten_users(users)
    base_cols = ["Nama SF", "Kode", "User ID", "Status Karyawan", "Nomor HP",
                 "Target Visit (Bulan)", "Target PS (Bulan)", "Target Mingguan",
                 "Total Assignment (Minggu)", "Kekurangan", "Status Rute"]
    cols = base_cols + day_headers
    ws1.append(["No"] + cols)
    for i, r in enumerate(rows, 1):
        ws1.append([i] + [r.get(c) for c in cols])

    ws2 = wb.create_sheet("Detail Homepass")
    ws2.append(["No"] + HOMEPASS_COLS)
    for i, r in enumerate(homepass_rows, 1):
        ws2.append([i] + [r.get(c) for c in HOMEPASS_COLS])

    return _safe_save(wb, out)


def write_combined_homepass(homepass_rows, d_from, d_to):
    out = os.path.join(OUTPUT_DIR, f"detail-homepass_{d_from}_sd_{d_to}.xlsx")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Detail Homepass"
    ws.append(["No"] + HOMEPASS_COLS)

    def _k(r):
        return (str(r.get("Tanggal") or ""), str(r.get("User ID") or ""), r.get("Urutan") or 0)

    for i, r in enumerate(sorted(homepass_rows, key=_k), 1):
        ws.append([i] + [r.get(c) for c in HOMEPASS_COLS])
    return _safe_save(wb, out)


# ==========================================
# ORKESTRASI SCRAPING
# ==========================================
def build_tasks(users, date_from=None, date_to=None):
    tasks = []
    for u in users:
        for a in (u.get("assignments") or []):
            try:
                tot = int(a.get("totalAssignment") or 0)
            except (TypeError, ValueError):
                tot = 0
            d = a.get("date")
            if not (tot > 0 and d):
                continue
            if date_from or date_to:
                try:
                    dd = datetime.date.fromisoformat(d[:10])
                except Exception:
                    continue
                if date_from and dd < date_from:
                    continue
                if date_to and dd > date_to:
                    continue
            tasks.append((u, d))
    return tasks


def monday_of(d):
    return d - datetime.timedelta(days=d.weekday())


def weeks_in_range(d_from, d_to):
    out, w = [], monday_of(d_from)
    while w <= d_to:
        out.append(w.isoformat())
        w += datetime.timedelta(weeks=1)
    return out


def _is_auth_error(err):
    low = (err or "").lower()
    return any(x in low for x in ["401", "403", "unauthorized", "autentifik", "nonce", "tidak terenkripsi", "token"])


def _is_key_error(err):
    return "decrypt" in (err or "").lower()


def reauth(headers, key, menu_id=None):
    print("\n  === TOKEN/SESI KADALUARSA — paste curl BARU untuk melanjutkan ===")
    print("  Buka lagi halaman detail SF di browser (masih login), Copy as cURL request sf-indihome,")
    print("  lalu paste di bawah. Kosongkan (Enter langsung) untuk berhenti & simpan progres.")
    raw = prompt_paste_curl("curl BARU (lanjut job)")
    if not raw.strip():
        return False, key
    _, ch = parse_curl_cmd(raw)
    if not header_get(ch, "authorization"):
        print("  [!] Authorization tidak ketemu di curl. Berhenti.")
        return False, key
    new_headers = replay_headers(ch)
    headers.clear()
    headers.update(new_headers)
    print("  [OK] Header auth diperbarui.")
    s = input("  Paste KUNCI AES baru (hex 64) kalau sesi login berganti, atau Enter pakai yang lama: ").strip()
    if s:
        if valid_key_hex(s):
            save_aes_key(s)
            key = bytes.fromhex(s)
            print("  [OK] Kunci AES diperbarui.")
        else:
            print("  [!] Format kunci salah (abaikan, pakai kunci lama).")
    return True, key


def run(session, base, headers, key, week_start, date_from=None, date_to=None, reauth_fn=None, reporting_headers=None):
    reauth_fn = reauth_fn or reauth
    reporting_base = reporting_base_url(base)
    print(f"\n=== DETAIL SF INDIHOME (bulk) weekStart={week_start} ===")

    users = load_weekly_cache(week_start)
    if users is not None:
        note_past = " [permanen: minggu lewat]" if is_past_week(week_start) else ""
        print(f"  [1/3] Daftar SF dari cache ({len(users)} SF){note_past}. (hapus _weekly_users.json atau "
              f"set DIGIPOS_SF_REFRESH_LIST=1 untuk ambil ulang)")
    else:
        print("  [1/3] Ambil daftar SF (weekly/user)...")
        def prog(done, total, n):
            print(f"      halaman {done}/{total} (total SF: {n})")
        while True:
            users, err = fetch_all_users(session, weekly_url(base), headers, key, week_start, on_progress=prog)
            if not err:
                save_weekly_cache(week_start, users)
                break
            print(f"  [!] Daftar SF tidak lengkap: {err}")
            if _is_auth_error(err) or _is_key_error(err):
                ok, key = reauth_fn(headers, key)
                if ok:
                    print("      Ulangi ambil daftar SF...")
                    continue
            if not users:
                return False, [], key
            print(f"      Lanjut dengan {len(users)} SF yang sempat terambil (tidak di-cache karena belum lengkap).")
            break

    tasks = build_tasks(users, date_from, date_to)
    sf_with = len({u.get('userId') for u, _ in tasks})
    rng = f" dalam rentang {date_from}..{date_to}" if (date_from or date_to) else ""
    print(f"  [2/3] {len(tasks)} (SF,hari) ber-assignment{rng} dari {sf_with} SF (dari total {len(users)} SF). "
          f"SF/hari tanpa assignment dilewati.")

    homepass_rows = []
    user_by_id = {u.get("userId"): u for u in users}
    sf_visit_maps = {}
    failed = False
    idx = 0
    while idx < len(tasks):
        user, date = tasks[idx]
        uid = str(user.get("userId"))
        period = str(date)[:7].replace("-", "")
        sf_period_key = (uid, period)

        if FETCH_VISITS and reporting_headers and sf_period_key not in sf_visit_maps:
            visits, key = fetch_sf_visits(session, reporting_base, reporting_headers, key, uid, period, reauth_fn)
            vmap = {}
            for v in visits:
                hp_id = str(v.get("homepassId") or "")
                v_date = str(v.get("checkInAt") or "")[:10]
                if hp_id and v_date:
                    vmap[(hp_id, v_date)] = v
                if hp_id and hp_id not in vmap:
                    vmap[hp_id] = v
            sf_visit_maps[sf_period_key] = vmap

        data = load_cache(week_start, uid, date)
        src = "cache"
        if data is None:
            j, ferr = get_decrypted(session, assignment_url(base, uid, date, week_start),
                                    headers, key, what=f"assignment {uid}/{date}")
            if ferr:
                print(f"  [!] Gagal assignment {uid} {date}: {ferr}")
                if _is_auth_error(ferr) or _is_key_error(ferr):
                    ok, key = reauth_fn(headers, key)
                    if ok:
                        continue
                else:
                    print("      (error non-auth; coba paste curl baru juga kalau mau lanjut.)")
                    ok, key = reauth_fn(headers, key)
                    if ok:
                        continue
                failed = True
                break
            data = j.get("data") or {}
            save_cache(week_start, uid, date, data)
            src = "server"
            time.sleep(REQUEST_DELAY)

        vmap = sf_visit_maps.get(sf_period_key, {})
        homepass_rows.extend(assignment_rows(user_by_id.get(user.get("userId"), user), date, data, visit_map=vmap))
        idx += 1
        if idx % 25 == 0 or idx == len(tasks):
            print(f"      {idx}/{len(tasks)} (homepass terkumpul: {len(homepass_rows)}) [{src}]")

    print("  [3/3] Tulis Excel minggu ini...")
    out = write_workbook(users, homepass_rows, week_start)
    note = "  [PARSIAL — jalankan lagi untuk melanjutkan]" if failed else ""
    print(f"  [OK] {len(users)} SF (ringkasan) + {len(homepass_rows)} homepass -> {out}{note}")
    return (not failed), homepass_rows, key


def choose_scope(curl_week):
    env_from = os.environ.get("DIGIPOS_SF_FROM", "").strip()
    env_to = os.environ.get("DIGIPOS_SF_TO", "").strip()

    def pd(s, default=None):
        s = (s or "").strip()
        return datetime.date.fromisoformat(s) if s else default

    if not env_from:
        base_hint = f"weekStart={curl_week}" if curl_week else "satu minggu (akan ditanya tanggalnya)"
        print(f"\n  Rentang tanggal. Kosongkan 'dari' untuk ambil SATU minggu ({base_hint}).")
        print("  Contoh sebulan: dari 2026-10-01 sampai (kosong = hari ini).")
        env_from = input("    Dari tanggal (YYYY-MM-DD): ").strip()
    try:
        if env_from:
            d_from = pd(env_from)
            d_to = pd(env_to, default=datetime.date.today())
            if not env_to:
                d_to = pd(input(f"    Sampai tanggal (YYYY-MM-DD) [Enter = hari ini {d_to}]: "), default=d_to)
            if d_to < d_from:
                print("  [!] 'sampai' lebih awal dari 'dari'.")
                return None
            return d_from, d_to, weeks_in_range(d_from, d_to)
        if curl_week:
            return None, None, [curl_week]
        wk = input("    weekStart satu minggu (YYYY-MM-DD, Senin): ").strip()
        if not wk:
            print("  [!] Tidak ada cakupan.")
            return None
        datetime.date.fromisoformat(wk)
        return None, None, [wk]
    except ValueError as e:
        print(f"  [!] Format tanggal salah: {e}")
        return None


def _run_all_weeks(session, base, headers, key_bytes, weeks, d_from, d_to, reauth_fn, reporting_headers=None):
    rng_txt = f"{d_from} s/d {d_to}" if d_from else f"minggu {weeks[0]}"
    print(f"\n  Cakupan: {rng_txt}  ->  {len(weeks)} minggu: {', '.join(weeks)}")
    all_hp, ok_all = [], True
    for i, wk in enumerate(weeks, 1):
        print(f"\n----- Minggu {i}/{len(weeks)} (weekStart={wk}) -----")
        ok, hp, key_bytes = run(session, base, headers, key_bytes, wk, d_from, d_to, reauth_fn=reauth_fn, reporting_headers=reporting_headers)
        all_hp.extend(hp)
        ok_all = ok_all and ok
        if not ok:
            print("  [!] Minggu ini berhenti. File gabungan tetap ditulis dari yang terkumpul.")
            break
    if d_from:
        out = write_combined_homepass(all_hp, d_from, d_to)
        print(f"\n  [GABUNGAN] {len(all_hp)} homepass {d_from}..{d_to} -> {out}")
    return ok_all


def main_auto(headless=False):
    """Mode OTOMATIS: buka Chrome (Playwright), ambil kunci AES + header sendiri, refresh otomatis."""
    auth = SfAuth(headless=headless).open()
    try:
        key_hex = auth.ensure_ready()
        if not key_hex:
            return False
        save_aes_key(key_hex)
        key_bytes = bytes.fromhex(key_hex)

        print("  Menangkap header request (Authorization + x-dgp-nonce + Cookie) dari halaman...")
        headers = auth.capture_headers()
        if not headers:
            print("  [!] Gagal menangkap header dari halaman.")
            return False
        print("  [OK] Header tertangkap.")

        reporting_headers = None
        if FETCH_VISITS:
            print("  Menyiapkan token otorisasi sf_visits (menu Laporan Kunjungan)...")
            vt = auth.get_token_for_menu("REV-DGP-PELAPORAN-VISIT-REPORT")
            if vt and vt.get("token"):
                reporting_headers = dict(headers)
                reporting_headers["Authorization"] = f"Bearer {vt['token']}"
                reporting_headers["x-dgp-nonce"] = vt.get("nonce") or headers.get("x-dgp-nonce")
                reporting_headers["Referer"] = "https://digipos.telkomsel.com/revamp/reporting-indihome/visit-report/sales-force/detail"
                print("  [OK] Token pelaporan sf_visits siap.")
            else:
                print("  [!] Gagal membuat token pelaporan. sf_visits akan dilewati.")

        def auto_reauth(hdrs, key, menu_id=None):
            print("  [auto] Token/nonce basi — ambil header segar dari browser...")
            nh = auth.capture_headers()
            if not nh:
                print("  [auto] Gagal ambil header segar (browser masih login?).")
                return False, key
            hdrs.clear()
            hdrs.update(nh)
            nk = auth.try_key()
            if nk and bytes.fromhex(nk) != key:
                save_aes_key(nk)
                key = bytes.fromhex(nk)
                print("  [auto] Kunci AES ikut diperbarui (sesi berganti).")
            if reporting_headers is not None:
                vt = auth.get_token_for_menu("REV-DGP-PELAPORAN-VISIT-REPORT")
                if vt and vt.get("token"):
                    reporting_headers["Authorization"] = f"Bearer {vt['token']}"
                    reporting_headers["x-dgp-nonce"] = vt.get("nonce") or nh.get("x-dgp-nonce")
                    if menu_id == "REV-DGP-PELAPORAN-VISIT-REPORT":
                        hdrs.clear()
                        hdrs.update(reporting_headers)
            print("  [auto] Lanjut.")
            return True, key

        scope = choose_scope(curl_week=None)
        if not scope:
            return False
        d_from, d_to, weeks = scope
        session = create_session()
        return _run_all_weeks(session, BASE_SCHEDULE, headers, key_bytes, weeks, d_from, d_to, auto_reauth, reporting_headers=reporting_headers)
    finally:
        auth.close()


def main_browser_only():
    """Hanya buka browser Chrome SELA (untuk login / cek sesi) tanpa menjalankan proses scraping."""
    print("\n" + "=" * 62)
    print("  MODE BROWSER SELA (Hanya Buka Chrome & Simpan Sesi Login)")
    print("=" * 62)
    auth = SfAuth(headless=False).open()
    try:
        key_hex = auth.ensure_ready(wait_seconds=1800)
        if key_hex:
            save_aes_key(key_hex)
            print("  [OK] Sesi login & kunci AES berhasil disimpan.")
        print("\n  Browser Chrome sedang terbuka.")
        print("  Tekan ENTER di terminal ini kapan saja untuk menyimpan sesi & menutup Chrome...")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        return True
    finally:
        auth.close()


def main_manual():
    """Mode MANUAL: paste curl + kunci AES dari config/snippet."""
    key = obtain_aes_key()
    if not key:
        print("  Dibatalkan (tidak ada kunci AES).")
        return False
    key_bytes = bytes.fromhex(key)

    raw = prompt_paste_curl("DETAIL SF INDIHOME (curl apa pun dari halaman detail, .../sf-indihome/schedule/...)")
    parsed_url, curl_headers = parse_curl_cmd(raw)
    url = extract_endpoint_url(raw, parsed_url)
    if not url:
        for m in re.finditer(r'(https?://[^\s"\'^]+sf-indihome/schedule[^\s"\'^]*)', raw):
            url = m.group(1).replace("^", "")
            break
    if not url or "sf-indihome/schedule" not in url:
        print("  [!] URL curl tidak sesuai (harus endpoint .../sf-indihome/schedule/...).")
        return False
    if not header_get(curl_headers, "authorization"):
        print("  [!] Header Authorization tidak ketemu di curl.")
        return False

    base = base_schedule_url(url)
    session = create_session()
    headers = replay_headers(curl_headers)

    reporting_headers = None
    if FETCH_VISITS:
        print("\n  [OPSIONAL] Endpoint sf_visits memerlukan token menu 'Laporan Kunjungan'.")
        print("  Buka menu Laporan Kunjungan di browser -> Copy as cURL salah satu request-nya.")
        print("  Tekan ENTER langsung untuk melewatkan sf_visits (hanya ambil detail assignment).")
        raw_rep = prompt_paste_curl("curl Laporan Kunjungan (opsional, tekan Enter untuk lewati)")
        if raw_rep.strip():
            _, rep_ch = parse_curl_cmd(raw_rep)
            if header_get(rep_ch, "authorization"):
                reporting_headers = replay_headers(rep_ch)
                print("  [OK] Header sf_visits (pelaporan) siap.")
            else:
                print("  [!] Authorization tidak ditemukan di curl pelaporan. sf_visits dilewati.")
        else:
            print("  [i] sf_visits dilewati.")

    scope = choose_scope(curl_week=get_week_start(url))
    if not scope:
        return False
    d_from, d_to, weeks = scope
    return _run_all_weeks(session, base, headers, key_bytes, weeks, d_from, d_to, reauth, reporting_headers=reporting_headers)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download DETAIL JADWAL SALES FORCE INDIHOME (bulk) dari Digipos SELA."
    )
    parser.add_argument("--auto", action="store_true",
                        help="Mode otomatis via browser Playwright (tangkap token & kunci AES sendiri)")
    parser.add_argument("--browser", "--login", dest="browser_only", action="store_true",
                        help="Hanya buka jendela Chrome SELA (untuk login/cek sesi) tanpa menjalankan scraping")
    parser.add_argument("--headless", action="store_true",
                        help="Browser berjalan di background tanpa jendela GUI (khusus --auto)")
    parser.add_argument("--size", type=int, default=None,
                        help="Jumlah data per halaman paginasi (default: 100)")
    parser.add_argument("--delay", type=float, default=None,
                        help="Jeda antar-request dalam detik (default: 0.6)")
    parser.add_argument("--from", dest="date_from", type=str, default=None,
                        help="Tanggal awal rentang (YYYY-MM-DD), misal 2026-10-01")
    parser.add_argument("--to", dest="date_to", type=str, default=None,
                        help="Tanggal akhir rentang (YYYY-MM-DD), default: hari ini")
    parser.add_argument("--no-visits", action="store_true",
                        help="Nonaktifkan pengambilan detail sf_visits (hanya ambil assignment homepass)")
    parser.add_argument("--refresh-list", action="store_true",
                        help="Paksa ambil ulang daftar SF dari server (abaikan cache _weekly_users.json)")
    parser.add_argument("--refresh-visits", action="store_true",
                        help="Paksa ambil ulang riwayat kunjungan sf_visits (abaikan cache sf_visits)")
    args, _ = parser.parse_known_args()
    return args


def main():
    global FETCH_VISITS, SIZE_OVERRIDE, REQUEST_DELAY
    args = parse_args()

    if args.size is not None:
        os.environ["DIGIPOS_SF_SIZE"] = str(args.size)
        SIZE_OVERRIDE = str(args.size)
    if args.delay is not None:
        os.environ["DIGIPOS_SF_DELAY"] = str(args.delay)
        REQUEST_DELAY = float(args.delay)
    if args.date_from:
        os.environ["DIGIPOS_SF_FROM"] = args.date_from
    if args.date_to:
        os.environ["DIGIPOS_SF_TO"] = args.date_to
    if args.no_visits:
        os.environ["DIGIPOS_SF_FETCH_VISITS"] = "0"
        FETCH_VISITS = False
    if args.refresh_list:
        os.environ["DIGIPOS_SF_REFRESH_LIST"] = "1"
    if args.refresh_visits:
        os.environ["DIGIPOS_SF_REFRESH_VISITS"] = "1"

    if args.browser_only:
        return main_browser_only()
    return main_auto(headless=args.headless) if args.auto else main_manual()


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
