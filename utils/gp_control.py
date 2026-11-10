"""
Kontrol GlobalProtect VPN (Windows) untuk /gp.

GlobalProtect di Windows tidak punya CLI resmi, tapi punya custom URL
protocol handler (`globalprotect://connect?portal=...`) yang beneran memicu
koneksi, bukan cuma buka GUI kosong. Kalau sesi/cert sudah tersimpan, GP
biasanya cuma perlu satu klik tombol "Connect" di window-nya — itu yang
disimulasikan lewat UI Automation (click_gp_connect.ps1).

Pendekatan ini diadaptasi dari implementasi yang sudah terbukti jalan di
proyek UTOIP DAILY (telegram_bot.py: handle_vpn_connect / check_vpn_status).

Kalau portal minta login SSO/2FA ulang (sesi expired), langkah di atas cuma
akan membuka jendela login di server — bot TIDAK mengisi kredensial apa pun,
itu harus dilakukan manual lewat RDP/console.
"""
import os
import subprocess
import time

GP_INSTALL_DIR = r"C:\Program Files\Palo Alto Networks\GlobalProtect"
GP_EXE = GP_INSTALL_DIR + r"\PanGPA.exe"
GP_EVENT_LOG = GP_INSTALL_DIR + r"\pan_gp_event.log"
GP_PORTAL = "sasa.telkomsel.co.id"

_CLICK_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "click_gp_connect.ps1")


def _is_proc_running(name: str) -> bool:
    try:
        res = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}"],
            capture_output=True, text=True, timeout=5,
        )
        return name.lower() in res.stdout.lower()
    except Exception:
        return False


def _adapter_connected() -> bool:
    """Cek adapter PANGP via ipconfig (ada IPv4, tidak 'Media disconnected')."""
    try:
        res = subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=5)
        out = res.stdout
        if "PANGP" not in out:
            return False
        lines = out.split("\n")
        for i, line in enumerate(lines):
            if "PANGP" in line:
                block = "\n".join(lines[i:i + 8])
                return "IPv4" in block and "Media disconnected" not in block
    except Exception:
        pass
    return False


def _last_log_event() -> tuple[str, bool | None]:
    """Baca event terakhir di pan_gp_event.log. Return (baris_terakhir, connected|None)."""
    if not os.path.exists(GP_EVENT_LOG):
        return "-", None
    try:
        with open(GP_EVENT_LOG, "r", errors="ignore") as f:
            content = f.read()
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        last_event = lines[-1] if lines else "-"

        last_conn = max(
            content.rfind("IPSec tunnel creation finished"),
            content.rfind("SSL tunnel creation finished"),
            content.rfind("Connected to Gateway"),
        )
        last_disconn = max(
            content.rfind("Tunnel is down"),
            content.rfind("User disconnecting tunnel"),
            content.rfind("User was logged out of Gateway"),
        )
        if last_conn > last_disconn and last_conn != -1:
            return last_event, True
        if last_disconn > last_conn and last_disconn != -1:
            return last_event, False
        return last_event, None
    except Exception:
        return "-", None


def get_status() -> dict:
    """
    Cek status GlobalProtect: proses, adapter, dan log event terakhir.
    connected = True kalau adapter aktif ATAU log terakhir bilang tunnel up.
    """
    gps = _is_proc_running("PanGPS.exe")
    gpa = _is_proc_running("PanGPA.exe")

    adapter_up = _adapter_connected()
    last_event, log_connected = _last_log_event()

    connected = adapter_up or bool(log_connected)

    return {
        "connected": connected,
        "pangps": gps,
        "pangpa": gpa,
        "last_event": last_event,
        "portal": GP_PORTAL,
    }


def _ensure_protocol_registered() -> None:
    """Daftarkan URL protocol handler globalprotect:// di HKCU kalau belum ada."""
    if os.name != "nt" or not os.path.exists(GP_EXE):
        return
    try:
        import winreg
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\globalprotect")
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:GlobalProtect Protocol")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        winreg.CloseKey(key)

        cmd_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\globalprotect\shell\open\command")
        winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, f'"{GP_EXE}" "%1"')
        winreg.CloseKey(cmd_key)
    except Exception:
        pass


def _click_connect_button() -> None:
    """Jalankan UI Automation buat cari & klik tombol 'Connect' di window GlobalProtect."""
    if os.name != "nt" or not os.path.exists(_CLICK_SCRIPT):
        return
    try:
        subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", _CLICK_SCRIPT],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        pass


def reconnect() -> None:
    """
    Coba nyambungin GlobalProtect: pastikan PanGPA jalan, trigger connect
    lewat protocol handler globalprotect://connect, lalu klik tombol
    Connect (UI Automation) sebagai fallback kalau butuh konfirmasi manual.
    """
    _ensure_protocol_registered()

    if not _is_proc_running("PanGPA.exe"):
        try:
            subprocess.Popen([GP_EXE], cwd=GP_INSTALL_DIR)
            time.sleep(1.0)
        except Exception:
            pass

    try:
        os.system(f"start globalprotect://connect?portal={GP_PORTAL}")
    except Exception:
        pass

    time.sleep(0.5)
    _click_connect_button()
