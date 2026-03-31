import base64
import hashlib
import json
import math
import os
import queue
import socket
import struct
import threading
import time
import zlib

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    ENCRYPTION_AVAILABLE = True
except Exception:
    AESGCM = None
    ENCRYPTION_AVAILABLE = False


BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "shared_files")
META_DIR = os.path.join(BASE_DIR, ".transfer_meta")
os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(META_DIR, exist_ok=True)

CONTROL_PORT = 9092
DATA_PORT = 9093
SOCKET_TIMEOUT = 12
DEFAULT_PARALLELISM = 4
DEFAULT_MAX_RETRIES = 3

MASTER_SECRET = os.getenv("TRANSFER_SECRET", "netshield-lan-secret").encode("utf-8")
MASTER_KEY = hashlib.sha256(MASTER_SECRET).digest()

_transfer_log = []
_log_lock = threading.Lock()
_sessions = {}
_session_lock = threading.Lock()
_server_started = False
_server_start_lock = threading.Lock()


def _recv_exact(sock, size):
    buf = bytearray()
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise ConnectionError("Socket closed while reading")
        buf.extend(chunk)
    return bytes(buf)


def _send_message(sock, payload):
    data = json.dumps(payload).encode("utf-8")
    sock.sendall(struct.pack("!I", len(data)) + data)


def _recv_message(sock):
    raw_len = _recv_exact(sock, 4)
    data_len = struct.unpack("!I", raw_len)[0]
    return json.loads(_recv_exact(sock, data_len).decode("utf-8"))


def _safe_name(filename):
    return os.path.basename(filename).replace("..", "_")


def _hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _session_key(transfer_id):
    return hashlib.sha256(MASTER_KEY + transfer_id.encode("utf-8")).digest()


def _now():
    return time.time()


def _meta_path(transfer_id):
    return os.path.join(META_DIR, f"{transfer_id}.json")


def _part_path(transfer_id):
    return os.path.join(META_DIR, f"{transfer_id}.part")


def _ensure_entry(direction, transfer_id, filename, size, addr, mode, parallelism, compression, encryption):
    with _log_lock:
        for entry in _transfer_log:
            if (
                entry["id"] == transfer_id
                and entry["direction"] == direction
                and entry["addr"] == addr
                and not entry["completed_at"]
            ):
                return entry
        entry = {
            "id": transfer_id,
            "filename": filename,
            "size": size,
            "direction": direction,
            "status": "Negotiating",
            "progress": 0,
            "addr": addr,
            "mode": mode,
            "parallelism": parallelism,
            "compression": compression,
            "encryption": encryption,
            "throughput_mbps": 0.0,
            "avg_rtt_ms": 0.0,
            "retries": 0,
            "chunk_loss_pct": 0.0,
            "compression_ratio": 1.0,
            "network_bytes": 0,
            "logical_bytes": 0,
            "started_at": _now(),
            "completed_at": None,
            "duration_sec": 0.0,
        }
        _transfer_log.append(entry)
        return entry


def _update_entry(entry, **changes):
    with _log_lock:
        entry.update(changes)


def _load_received_chunks(meta):
    return set(meta.get("received_chunks", []))


def _save_meta(session):
    payload = {
        "transfer_id": session["transfer_id"],
        "filename": session["filename"],
        "file_sha256": session["file_sha256"],
        "filesize": session["filesize"],
        "chunk_size": session["chunk_size"],
        "total_chunks": session["total_chunks"],
        "received_chunks": sorted(session["received_chunks"]),
        "mode": session["mode"],
        "parallelism": session["parallelism"],
        "compression": session["compression"],
        "encryption": session["encryption"],
        "created_at": session["created_at"],
        "updated_at": _now(),
    }
    with open(session["meta_path"], "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _mark_complete(entry, success, status):
    duration = max(0.001, _now() - entry["started_at"])
    throughput = (entry["logical_bytes"] / 1024 / 1024) / duration
    _update_entry(
        entry,
        status=status,
        progress=100 if success else entry["progress"],
        completed_at=_now(),
        duration_sec=round(duration, 2),
        throughput_mbps=round(throughput, 2),
    )


def _get_session(transfer_id):
    with _session_lock:
        return _sessions.get(transfer_id)


def _put_session(transfer_id, session):
    with _session_lock:
        _sessions[transfer_id] = session


def _build_receive_session(meta, addr):
    transfer_id = meta["transfer_id"]
    session = _get_session(transfer_id)
    if session:
        return session

    meta_file = _meta_path(transfer_id)
    loaded = {}
    if os.path.exists(meta_file):
        with open(meta_file, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)

    final_path = os.path.join(BASE_DIR, _safe_name(meta["filename"]))
    if os.path.exists(final_path):
        try:
            if _hash_file(final_path) == meta["file_sha256"]:
                loaded = {
                    "received_chunks": list(range(meta["total_chunks"])),
                    "chunk_size": meta["chunk_size"],
                    "total_chunks": meta["total_chunks"],
                }
        except OSError:
            pass

    session = {
        "transfer_id": transfer_id,
        "filename": _safe_name(meta["filename"]),
        "file_sha256": meta["file_sha256"],
        "filesize": meta["filesize"],
        "chunk_size": meta["chunk_size"],
        "total_chunks": meta["total_chunks"],
        "received_chunks": _load_received_chunks(loaded),
        "mode": meta["mode"],
        "parallelism": meta["parallelism"],
        "compression": meta["compression"],
        "encryption": meta["encryption"],
        "created_at": loaded.get("created_at", _now()),
        "meta_path": meta_file,
        "part_path": _part_path(transfer_id),
        "final_path": final_path,
        "file_lock": threading.Lock(),
        "entry": _ensure_entry(
            "↓ IN",
            transfer_id,
            _safe_name(meta["filename"]),
            meta["filesize"],
            str(addr),
            meta["mode"],
            meta["parallelism"],
            meta["compression"],
            meta["encryption"],
        ),
    }
    if not os.path.exists(session["part_path"]):
        with open(session["part_path"], "wb") as handle:
            handle.truncate(session["filesize"])
    else:
        current_size = os.path.getsize(session["part_path"])
        if current_size != session["filesize"]:
            with open(session["part_path"], "wb") as handle:
                handle.truncate(session["filesize"])
            session["received_chunks"].clear()

    _save_meta(session)
    _put_session(transfer_id, session)

    progress = int(len(session["received_chunks"]) / max(1, session["total_chunks"]) * 100)
    _update_entry(session["entry"], status="Ready to receive", progress=progress)
    return session


def _handle_control(conn, addr):
    try:
        conn.settimeout(SOCKET_TIMEOUT)
        message = _recv_message(conn)
        action = message.get("action")

        if action == "init":
            transfer_id = message["file_sha256"][:16]
            session = _build_receive_session(
                {
                    "transfer_id": transfer_id,
                    "filename": message["filename"],
                    "file_sha256": message["file_sha256"],
                    "filesize": message["filesize"],
                    "chunk_size": message["chunk_size"],
                    "total_chunks": message["total_chunks"],
                    "mode": message["mode"],
                    "parallelism": message["parallelism"],
                    "compression": message["compression"],
                    "encryption": message["encryption"],
                },
                addr[0],
            )
            missing = sorted(set(range(session["total_chunks"])) - session["received_chunks"])
            _send_message(
                conn,
                {
                    "ok": True,
                    "transfer_id": transfer_id,
                    "missing_chunks": missing,
                    "completed": not missing,
                    "resume_supported": True,
                    "data_port": DATA_PORT,
                },
            )
            return

        if action == "finalize":
            session = _get_session(message["transfer_id"])
            if not session:
                _send_message(conn, {"ok": False, "error": "Unknown transfer"})
                return

            missing = sorted(set(range(session["total_chunks"])) - session["received_chunks"])
            if missing:
                _send_message(conn, {"ok": False, "error": f"Missing chunks: {len(missing)}"})
                return

            digest = _hash_file(session["part_path"])
            if digest != session["file_sha256"]:
                _send_message(conn, {"ok": False, "error": "Final SHA256 verification failed"})
                _update_entry(session["entry"], status="❌ SHA256 verification failed")
                return

            os.replace(session["part_path"], session["final_path"])
            if os.path.exists(session["meta_path"]):
                os.remove(session["meta_path"])
            _mark_complete(session["entry"], True, "✅ Complete")
            _send_message(conn, {"ok": True, "path": session["final_path"]})
            return

        _send_message(conn, {"ok": False, "error": "Unsupported control action"})
    except Exception as exc:
        try:
            _send_message(conn, {"ok": False, "error": str(exc)})
        except Exception:
            pass
    finally:
        conn.close()


def _handle_chunk_connection(conn, addr):
    started = _now()
    try:
        conn.settimeout(SOCKET_TIMEOUT)
        header = _recv_message(conn)
        payload = _recv_exact(conn, header["payload_size"])
        session = _get_session(header["transfer_id"])
        if not session:
            raise ValueError("Transfer session not found")

        plaintext = payload
        if header["encrypted"]:
            if not ENCRYPTION_AVAILABLE:
                raise RuntimeError("Receiver encryption support is unavailable")
            nonce = base64.b64decode(header["nonce"])
            aesgcm = AESGCM(_session_key(header["transfer_id"]))
            plaintext = aesgcm.decrypt(nonce, payload, None)
        if header["compressed"]:
            plaintext = zlib.decompress(plaintext)

        checksum = hashlib.sha256(plaintext).hexdigest()
        if checksum != header["checksum"]:
            raise ValueError("Checksum mismatch")

        if len(plaintext) != header["original_size"]:
            raise ValueError("Chunk length mismatch")

        with session["file_lock"]:
            with open(session["part_path"], "r+b") as handle:
                handle.seek(header["offset"])
                handle.write(plaintext)
            session["received_chunks"].add(header["chunk_index"])
            _save_meta(session)

        progress = int(len(session["received_chunks"]) / max(1, session["total_chunks"]) * 100)
        entry = session["entry"]
        network_bytes = entry["network_bytes"] + header["payload_size"]
        logical_bytes = entry["logical_bytes"] + header["original_size"]
        ratio = network_bytes / max(1, logical_bytes)
        _update_entry(
            entry,
            status="Receiving chunks",
            progress=progress,
            network_bytes=network_bytes,
            logical_bytes=logical_bytes,
            compression_ratio=round(ratio, 3),
        )

        elapsed_ms = round((_now() - started) * 1000, 2)
        _send_message(conn, {"ok": True, "chunk_index": header["chunk_index"], "rtt_ms": elapsed_ms})
    except Exception as exc:
        try:
            _send_message(conn, {"ok": False, "error": str(exc)})
        except Exception:
            pass
    finally:
        conn.close()


def _serve_control():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", CONTROL_PORT))
    srv.listen(20)
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=_handle_control, args=(conn, addr), daemon=True).start()


def _serve_data():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", DATA_PORT))
    srv.listen(50)
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=_handle_chunk_connection, args=(conn, addr), daemon=True).start()


def start_file_server():
    global _server_started
    with _server_start_lock:
        if _server_started:
            return
        threading.Thread(target=_serve_control, daemon=True).start()
        threading.Thread(target=_serve_data, daemon=True).start()
        _server_started = True


def _chunk_plaintext(filepath, chunk_size, chunk_index):
    offset = chunk_index * chunk_size
    with open(filepath, "rb") as handle:
        handle.seek(offset)
        data = handle.read(chunk_size)
    return offset, data


def _open_control_socket(target_ip):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(SOCKET_TIMEOUT)
    sock.connect((target_ip, CONTROL_PORT))
    return sock


def _send_chunk(target_ip, transfer_id, chunk_index, offset, data, use_compression, use_encryption):
    checksum = hashlib.sha256(data).hexdigest()
    payload = data
    compressed = False
    if use_compression:
        compressed_payload = zlib.compress(data, level=6)
        if len(compressed_payload) < len(data):
            payload = compressed_payload
            compressed = True

    nonce = ""
    encrypted = False
    if use_encryption:
        aesgcm = AESGCM(_session_key(transfer_id))
        nonce_bytes = os.urandom(12)
        payload = aesgcm.encrypt(nonce_bytes, payload, None)
        nonce = base64.b64encode(nonce_bytes).decode("utf-8")
        encrypted = True

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(SOCKET_TIMEOUT)
    started = _now()
    try:
        sock.connect((target_ip, DATA_PORT))
        _send_message(
            sock,
            {
                "transfer_id": transfer_id,
                "chunk_index": chunk_index,
                "offset": offset,
                "original_size": len(data),
                "payload_size": len(payload),
                "checksum": checksum,
                "compressed": compressed,
                "encrypted": encrypted,
                "nonce": nonce,
            },
        )
        sock.sendall(payload)
        ack = _recv_message(sock)
        ack.setdefault("rtt_ms", round((_now() - started) * 1000, 2))
        return ack, len(payload)
    finally:
        sock.close()


def send_file(
    target_ip,
    filepath,
    mode="parallel",
    parallelism=DEFAULT_PARALLELISM,
    chunk_size_kb=256,
    compression=True,
    encryption=True,
    max_retries=DEFAULT_MAX_RETRIES,
):
    if not os.path.exists(filepath):
        return False, "File not found"

    mode = "parallel" if mode == "parallel" else "normal"
    parallelism = max(1, int(parallelism or 1))
    if mode == "normal":
        parallelism = 1
    if encryption and not ENCRYPTION_AVAILABLE:
        return False, "Encryption requested but cryptography is not installed on this machine"

    chunk_size = max(64, int(chunk_size_kb or 256)) * 1024
    max_retries = max(1, int(max_retries or DEFAULT_MAX_RETRIES))

    filename = _safe_name(filepath)
    filesize = os.path.getsize(filepath)
    file_sha256 = _hash_file(filepath)
    total_chunks = max(1, math.ceil(filesize / chunk_size))
    transfer_id = file_sha256[:16]

    entry = _ensure_entry(
        "↑ OUT",
        transfer_id,
        filename,
        filesize,
        target_ip,
        mode,
        parallelism,
        bool(compression),
        bool(encryption),
    )
    _update_entry(entry, status="Negotiating session")

    try:
        sock = _open_control_socket(target_ip)
        _send_message(
            sock,
            {
                "action": "init",
                "filename": filename,
                "filesize": filesize,
                "file_sha256": file_sha256,
                "chunk_size": chunk_size,
                "total_chunks": total_chunks,
                "mode": mode,
                "parallelism": parallelism,
                "compression": bool(compression),
                "encryption": bool(encryption),
            },
        )
        response = _recv_message(sock)
        sock.close()
        if not response.get("ok"):
            _update_entry(entry, status=f"❌ {response.get('error', 'Handshake failed')}")
            return False, response.get("error", "Handshake failed")
    except Exception as exc:
        _update_entry(entry, status=f"❌ Handshake failed: {exc}")
        return False, f"Handshake failed: {exc}"

    if response.get("completed"):
        _mark_complete(entry, True, "✅ Already present on receiver")
        return True, "Receiver already has this file"

    missing_chunks = queue.Queue()
    for chunk_index in response["missing_chunks"]:
        missing_chunks.put(chunk_index)

    expected_chunks = len(response["missing_chunks"])
    state = {
        "acked": 0,
        "retries": 0,
        "failures": 0,
        "payload_bytes": 0,
        "logical_bytes": 0,
        "rtts": [],
        "lock": threading.Lock(),
        "error": None,
    }

    _update_entry(entry, status="Sending chunks", progress=0)

    def worker():
        while state["error"] is None:
            try:
                chunk_index = missing_chunks.get_nowait()
            except queue.Empty:
                return

            offset, data = _chunk_plaintext(filepath, chunk_size, chunk_index)
            success = False
            attempts = 0
            while attempts < max_retries and not success:
                attempts += 1
                try:
                    ack, payload_size = _send_chunk(
                        target_ip,
                        transfer_id,
                        chunk_index,
                        offset,
                        data,
                        bool(compression),
                        bool(encryption),
                    )
                    if not ack.get("ok"):
                        raise ValueError(ack.get("error", "Chunk rejected"))

                    with state["lock"]:
                        state["acked"] += 1
                        state["logical_bytes"] += len(data)
                        state["payload_bytes"] += payload_size
                        state["rtts"].append(ack.get("rtt_ms", 0.0))
                        if attempts > 1:
                            state["retries"] += attempts - 1
                        progress = int(state["acked"] / max(1, expected_chunks) * 100)
                        avg_rtt = sum(state["rtts"]) / max(1, len(state["rtts"]))
                        chunk_loss = state["retries"] / max(1, state["acked"] + state["retries"]) * 100
                        ratio = state["payload_bytes"] / max(1, state["logical_bytes"])
                        _update_entry(
                            entry,
                            progress=progress,
                            retries=state["retries"],
                            avg_rtt_ms=round(avg_rtt, 2),
                            chunk_loss_pct=round(chunk_loss, 2),
                            network_bytes=state["payload_bytes"],
                            logical_bytes=state["logical_bytes"],
                            compression_ratio=round(ratio, 3),
                        )
                    success = True
                except Exception:
                    if attempts >= max_retries:
                        with state["lock"]:
                            state["retries"] += max(0, attempts - 1)
                            state["failures"] += 1
                            state["error"] = f"Chunk {chunk_index} failed after {max_retries} attempts"

            missing_chunks.task_done()

    threads = [
        threading.Thread(target=worker, daemon=True)
        for _ in range(min(parallelism, max(1, expected_chunks)))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    if state["error"] is not None:
        _update_entry(entry, status=f"❌ {state['error']}")
        return False, state["error"]

    try:
        sock = _open_control_socket(target_ip)
        _send_message(sock, {"action": "finalize", "transfer_id": transfer_id})
        finalize = _recv_message(sock)
        sock.close()
        if not finalize.get("ok"):
            _update_entry(entry, status=f"❌ Finalize failed: {finalize.get('error')}")
            return False, finalize.get("error", "Finalize failed")
    except Exception as exc:
        _update_entry(entry, status=f"❌ Finalize failed: {exc}")
        return False, f"Finalize failed: {exc}"

    _mark_complete(entry, True, "✅ Complete")
    return True, "Transfer completed"


def schedule_transfers(
    target_ips,
    filepath,
    mode="parallel",
    parallelism=DEFAULT_PARALLELISM,
    chunk_size_kb=256,
    compression=True,
    encryption=True,
    max_retries=DEFAULT_MAX_RETRIES,
):
    if isinstance(target_ips, str):
        parsed = [target.strip() for target in target_ips.replace("\n", ",").split(",") if target.strip()]
    else:
        parsed = [str(target).strip() for target in target_ips if str(target).strip()]

    unique_targets = []
    seen = set()
    for target in parsed:
        if target not in seen:
            unique_targets.append(target)
            seen.add(target)

    if not unique_targets:
        return False, "Enter at least one target IP address"
    if not os.path.exists(filepath):
        return False, "File not found"

    def _launch(target_ip):
        send_file(
            target_ip,
            filepath,
            mode=mode,
            parallelism=parallelism,
            chunk_size_kb=chunk_size_kb,
            compression=compression,
            encryption=encryption,
            max_retries=max_retries,
        )

    for target_ip in unique_targets:
        threading.Thread(target=_launch, args=(target_ip,), daemon=True).start()

    if len(unique_targets) == 1:
        return True, f"Transfer queued for {unique_targets[0]}"
    return True, f"Transfer queued for {len(unique_targets)} target devices"


def get_transfers():
    with _log_lock:
        entries = list(reversed(_transfer_log[-20:]))
    output = []
    for entry in entries:
        item = dict(entry)
        if item["completed_at"] and item["started_at"]:
            item["duration_sec"] = round(item["completed_at"] - item["started_at"], 2)
        output.append(item)
    return output


def get_transfer_summary():
    with _log_lock:
        entries = [dict(entry) for entry in _transfer_log if entry["direction"] == "↑ OUT" and entry["completed_at"]]

    def _mode_summary(mode):
        rows = [row for row in entries if row["mode"] == mode]
        if not rows:
            return {
                "count": 0,
                "avg_throughput_mbps": 0.0,
                "avg_duration_sec": 0.0,
                "avg_rtt_ms": 0.0,
            }
        return {
            "count": len(rows),
            "avg_throughput_mbps": round(sum(r["throughput_mbps"] for r in rows) / len(rows), 2),
            "avg_duration_sec": round(sum(r["duration_sec"] for r in rows) / len(rows), 2),
            "avg_rtt_ms": round(sum(r["avg_rtt_ms"] for r in rows) / len(rows), 2),
        }

    return {
        "normal": _mode_summary("normal"),
        "parallel": _mode_summary("parallel"),
    }
