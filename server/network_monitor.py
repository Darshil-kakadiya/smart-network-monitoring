import psutil
import socket
import time
import threading
import random

try:
    from scapy.all import ARP, Ether, srp
    SCAPY_AVAILABLE = True
except:
    SCAPY_AVAILABLE = False

# ─── Bandwidth ────────────────────────────────────────────────────────────────
_prev_io = psutil.net_io_counters()
_prev_time = time.time()
_speed_lock = threading.Lock()
_current_speed = {"upload": 0.0, "download": 0.0}

def _speed_sampler():
    global _prev_io, _prev_time
    while True:
        time.sleep(1)
        now = psutil.net_io_counters()
        elapsed = time.time() - _prev_time
        with _speed_lock:
            _current_speed["upload"]   = (now.bytes_sent - _prev_io.bytes_sent) / elapsed / 1024 / 1024
            _current_speed["download"] = (now.bytes_recv - _prev_io.bytes_recv) / elapsed / 1024 / 1024
        _prev_io   = now
        _prev_time = time.time()

threading.Thread(target=_speed_sampler, daemon=True).start()


def get_bandwidth():
    with _speed_lock:
        return dict(_current_speed)


# ─── Device Discovery ─────────────────────────────────────────────────────────
_known_devices = {}
_device_lock   = threading.Lock()


def _classify_device(ip: str) -> str:
    last = int(ip.split(".")[-1])
    if last == 1:   return "🌐 Router"
    if last < 20:   return "🖥️ Server"
    return random.choice(["💻 Workstation", "📱 Mobile", "🖨️ Printer", "📡 IoT"])


def _scan_arp(subnet: str):
    if not SCAPY_AVAILABLE:
        return _mock_devices()
    try:
        pkt = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=subnet)
        ans, _ = srp(pkt, timeout=2, verbose=0)
        found = {}
        for _, r in ans:
            ip, mac = r.psrc, r.hwsrc
            found[mac] = {
                "ip": ip, "mac": mac,
                "type": _classify_device(ip),
                "status": "🟢 Online",
                "first_seen": _known_devices.get(mac, {}).get("first_seen", int(time.time())),
            }
        return found
    except Exception as e:
        return _mock_devices()


def _mock_devices():
    return {
        "00:11:22:33:44:01": {"ip": "192.168.1.1",   "mac": "00:11:22:33:44:01", "type": "🌐 Router",      "status": "🟢 Online", "first_seen": int(time.time())-300},
        "00:11:22:33:44:02": {"ip": "192.168.1.102", "mac": "00:11:22:33:44:02", "type": "💻 Workstation", "status": "🟢 Online", "first_seen": int(time.time())-120},
        "00:11:22:33:44:03": {"ip": "192.168.1.105", "mac": "00:11:22:33:44:03", "type": "📱 Mobile",      "status": "🟡 Idle",   "first_seen": int(time.time())-60},
    }


def _auto_subnet():
    """Best-guess the local /24 subnet."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        parts = local_ip.rsplit(".", 1)
        return f"{parts[0]}.0/24"
    except:
        return "192.168.1.0/24"


def _scanner_loop():
    global _known_devices
    subnet = _auto_subnet()
    while True:
        found = _scan_arp(subnet)
        with _device_lock:
            _known_devices = found
        time.sleep(10)

threading.Thread(target=_scanner_loop, daemon=True).start()


def get_devices():
    with _device_lock:
        return list(_known_devices.values())


# ─── System Stats ─────────────────────────────────────────────────────────────
def get_system_stats():
    cpu    = psutil.cpu_percent(interval=None)
    ram    = psutil.virtual_memory().percent
    return {"cpu": cpu, "ram": ram}
