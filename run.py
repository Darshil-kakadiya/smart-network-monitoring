"""
NetShield LAN v2.0
Run this file to start the full system.
"""
import os

from server.app import socketio, app


APP_PORT = int(os.getenv("APP_PORT", "5050"))

if __name__ == "__main__":
    print("\n  ╔══════════════════════════════════════════╗")
    print("  ║  NetShield LAN v2.0                    ║")
    print(f"  ║  Open: http://localhost:{APP_PORT}            ║")
    print("  ║  Login: admin / netshield               ║")
    print("  ╚══════════════════════════════════════════╝\n")
    socketio.run(app, host="0.0.0.0", port=APP_PORT, debug=False, allow_unsafe_werkzeug=True)
