import time
import random
import math

# ─── AI Engine ─────────────────────────────────────────────────────────────────

class AIEngine:
    def __init__(self):
        self.history = []         # list of (timestamp, upload_mb, download_mb, device_count)
        self.alert_log = []
        self.anomaly_count = 0

    # ── Feed telemetry ────────────────────────────────────────────────────────
    def feed(self, upload, download, device_count):
        record = (time.time(), upload, download, device_count)
        self.history.append(record)
        if len(self.history) > 300:
            self.history.pop(0)
        self._analyse(upload, download, device_count)

    def _analyse(self, upload, download, device_count):
        alerts = []
        if device_count > 8:
            alerts.append("⚠️ High device count — possible unauthorized access!")
        if upload > 5 or download > 10:
            alerts.append("🚨 High traffic detected — bandwidth spike!")
        if device_count > 5:
            alerts.append("⚠️ Suspicious activity — more than 5 devices on LAN.")
        if alerts:
            for a in alerts:
                if not self.alert_log or self.alert_log[-1]["msg"] != a:
                    self.alert_log.append({"time": time.strftime("%H:%M:%S"), "msg": a})
            self.anomaly_count += 1
        else:
            self.anomaly_count = max(0, self.anomaly_count - 1)
        if len(self.alert_log) > 20:
            self.alert_log = self.alert_log[-20:]

    def security_level(self):
        if self.anomaly_count == 0:   return "🟢 Secure"
        if self.anomaly_count < 3:    return "🟡 Caution"
        return "🔴 Threat Detected"

    def get_alerts(self):
        return list(reversed(self.alert_log))

    # ── Chatbot ───────────────────────────────────────────────────────────────
    _KB = {
        "/status":   lambda s: f"Server is ONLINE | Anomaly count: {s.anomaly_count} | Security: {s.security_level()}",
        "/devices":  lambda s: f"Currently tracking devices. Last alert: {s.alert_log[-1]['msg'] if s.alert_log else 'None'}",
        "/security": lambda s: f"Security Level: {s.security_level()}. Recent alerts: {len(s.alert_log)}",
        "/help":     lambda s: "Commands: /status · /devices · /security · /clear · /tips",
        "/clear":    lambda s: "Alert log cleared.",
        "/tips":     lambda s: (
            "💡 Tip: Use Parallel Transfer for large files.\n"
            "💡 Keep your device list under 5 for optimal security.\n"
            "💡 Monitor spikes above 10 MB/s regularly."
        ),
        "tcp":       lambda s: "📡 TCP is a reliable, connection-oriented protocol.",
        "udp":       lambda s: "⚡ UDP is connectionless and low-latency — great for streaming.",
        "arp":       lambda s: "🔍 ARP maps IP addresses to MAC addresses on the LAN.",
    }

    def respond(self, query: str) -> str:
        q = query.strip().lower()
        if q == "/clear":
            self.alert_log.clear()
        for key, fn in self._KB.items():
            if q.startswith(key) or key in q:
                return fn(self)
        return f"🤖 I don't know about '{query}'. Try /help for commands."


ai_engine = AIEngine()
