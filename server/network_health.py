from collections import deque


_history = deque([85.0] * 60, maxlen=60)


def _clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def _latest_transfer_metric(transfers, key):
    for item in transfers:
        if item.get("direction") == "↑ OUT" and item.get(key) is not None:
            return float(item.get(key, 0.0) or 0.0)
    for item in transfers:
        if item.get(key) is not None:
            return float(item.get(key, 0.0) or 0.0)
    return 0.0


def get_network_health(upload, download, device_count, cpu, ram, transfers):
    traffic_load = _clamp((upload + download) * 8.0, 0.0, 100.0)
    rtt_ms = _latest_transfer_metric(transfers, "avg_rtt_ms")
    retry_count = _latest_transfer_metric(transfers, "retries")
    loss_pct = _latest_transfer_metric(transfers, "chunk_loss_pct")

    score = 100.0
    score -= cpu * 0.20
    score -= ram * 0.12
    score -= traffic_load * 0.18
    score -= max(0, device_count - 5) * 3.5
    score -= min(20.0, rtt_ms / 4.0)
    score -= min(20.0, loss_pct * 3.0)
    score -= min(10.0, retry_count * 1.5)
    score = _clamp(score)

    if score >= 85:
        status = "Excellent"
    elif score >= 70:
        status = "Good"
    elif score >= 50:
        status = "Busy"
    else:
        status = "Critical"

    _history.append(score)

    return {
        "score": round(score, 1),
        "load": round(traffic_load, 1),
        "avg_rtt_ms": round(rtt_ms, 2),
        "status": status,
        "history": list(_history),
    }
