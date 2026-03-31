"""
NetShield LAN Dashboard - Flask + SocketIO Server
Fully real-time: all panels update every 1 second via WebSocket.
"""
import os, sys, threading, time

# ── path fix so sub-modules can import each other ────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session, flash)
from flask_socketio import SocketIO, emit

from server.network_monitor import get_bandwidth, get_devices, get_system_stats
from server.ai_engine       import ai_engine
from server.file_transfer   import (
    start_file_server,
    schedule_transfers,
    get_transfers,
    get_transfer_summary,
)
from server.network_health   import get_network_health

# ── App setup ─────────────────────────────────────────────────────────────────
app     = Flask(__name__,
                template_folder=os.path.join(ROOT, "templates"),
                static_folder  =os.path.join(ROOT, "static"))
app.secret_key = "netshield-secret-2026"

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
APP_PORT = int(os.getenv("APP_PORT", "5050"))

# Simple admin creds (extend to DB as needed)
ADMIN_USER = "admin"
ADMIN_PASS = "netshield"

# ── Auth routes ───────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username")
        p = request.form.get("password")
        if u == ADMIN_USER and p == ADMIN_PASS:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        flash("Invalid credentials")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route("/")
def dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return render_template("index.html")

# ── REST endpoints ─────────────────────────────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
def chat():
    query = request.json.get("query", "")
    reply = ai_engine.respond(query)
    return jsonify({"reply": reply})

@app.route("/api/sendfile", methods=["POST"])
def api_sendfile():
    target_ip = request.json.get("target_ip", "")
    file_path = request.json.get("file_path", "")
    mode = request.json.get("mode", "parallel")
    parallelism = request.json.get("parallelism", 4)
    chunk_size_kb = request.json.get("chunk_size_kb", 256)
    compression = request.json.get("compression", True)
    encryption = request.json.get("encryption", True)
    max_retries = request.json.get("max_retries", 3)
    ok, msg   = schedule_transfers(
        target_ip,
        file_path,
        mode=mode,
        parallelism=parallelism,
        chunk_size_kb=chunk_size_kb,
        compression=compression,
        encryption=encryption,
        max_retries=max_retries,
    )
    return jsonify({"ok": ok, "msg": msg})

# ── Real-time push: broadcast every 1 second ──────────────────────────────────
def _broadcast_loop():
    while True:
        try:
            bw      = get_bandwidth()
            devices = get_devices()
            sys_s   = get_system_stats()
            ai_engine.feed(bw["upload"], bw["download"], len(devices))
            transfers = get_transfers()
            network_health = get_network_health(
                bw["upload"],
                bw["download"],
                len(devices),
                sys_s["cpu"],
                sys_s["ram"],
                transfers,
            )

            payload = {
                "upload":   round(bw["upload"],   2),
                "download": round(bw["download"], 2),
                "device_count": len(devices),
                "security": ai_engine.security_level(),
                "alerts":   ai_engine.get_alerts()[:5],
                "devices":  devices,
                "cpu":      sys_s["cpu"],
                "ram":      sys_s["ram"],
                "transfers": transfers,
                "transfer_summary": get_transfer_summary(),
                "network_health": network_health,
            }
            socketio.emit("update", payload)
        except Exception as e:
            pass
        time.sleep(1)

# ── Start background threads ──────────────────────────────────────────────────
threading.Thread(target=_broadcast_loop,  daemon=True).start()
threading.Thread(target=start_file_server, daemon=True).start()

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n  ╔══════════════════════════════════════════╗")
    print("  ║  NetShield LAN v2.0                    ║")
    print(f"  ║  Dashboard → http://localhost:{APP_PORT}      ║")
    print("  ╚══════════════════════════════════════════╝\n")
    socketio.run(app, host="0.0.0.0", port=APP_PORT, debug=False, allow_unsafe_werkzeug=True)
