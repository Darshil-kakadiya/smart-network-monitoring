/* ══════════════════════════════════════════════════════════════════════════
   NetShield LAN Dashboard Logic
   Handles real-time SocketIO updates, streaming charts, and interactions.
══════════════════════════════════════════════════════════════════════════ */

// ── Clock ──────────────────────────────────────────────────────────────────
function updateClock() {
    const now = new Date();
    const options = { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' };
    document.getElementById("clock").textContent = now.toLocaleDateString('en-US', options).toUpperCase();
}
setInterval(updateClock, 1000);
updateClock();

// ── Chart Defaults ────────────────────────────────────────────────────────
Chart.defaults.color = 'hsl(210, 10%, 65%)';
Chart.defaults.font.family = "'Inter', sans-serif";

// ── Network Speed Chart ────────────────────────────────────────────────────
const netCtx = document.getElementById("netChart").getContext("2d");
const netChart = new Chart(netCtx, {
    type: "line",
    data: {
        labels: Array(60).fill(""),
        datasets: [
            {
                label: "UPLINK (MB/s)",
                data: Array(60).fill(0),
                borderColor: "hsl(180, 100%, 50%)",
                backgroundColor: "hsla(180, 100%, 50%, 0.1)",
                fill: true, tension: 0.4, borderWidth: 2, pointRadius: 0
            },
            {
                label: "DOWNLINK (MB/s)",
                data: Array(60).fill(0),
                borderColor: "hsl(270, 70%, 60%)",
                backgroundColor: "hsla(270, 70%, 60%, 0.1)",
                fill: true, tension: 0.4, borderWidth: 2, pointRadius: 0
            }
        ]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 800, easing: 'easeOutQuart' },
        scales: {
            x: { display: false },
            y: { 
                beginAtZero: true,
                grid: { color: "hsla(230, 40%, 40%, 0.1)" },
                ticks: { font: { size: 10, weight: 'bold' } }
            }
        },
        plugins: {
            legend: { position: 'top', align: 'end', labels: { boxWidth: 12, usePointStyle: true, font: { size: 11 } } }
        }
    }
});

// ── Network Health Chart ──────────────────────────────────────────────────
const healthCtx = document.getElementById("healthChart").getContext("2d");
const healthChart = new Chart(healthCtx, {
    type: "line",
    data: {
        labels: Array(60).fill(""),
        datasets: [{
            label: "HEALTH SCORE %",
            data: Array(60).fill(80),
            borderColor: "hsl(150, 100%, 50%)",
            backgroundColor: "hsla(150, 100%, 50%, 0.1)",
            fill: true, tension: 0.5, borderWidth: 3, pointRadius: 0
        }]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 1000 },
        scales: {
            x: { display: false },
            y: { 
                min: 0, max: 100,
                grid: { color: "hsla(230, 40%, 40%, 0.05)" },
                ticks: { display: false }
            }
        },
        plugins: { legend: { display: false } }
    }
});

// ── SocketIO Integration ──────────────────────────────────────────────────
const socket = io();

socket.on("update", (data) => {
    // 1. KPI Updates
    document.getElementById("kpi-upload").textContent   = data.upload.toFixed(2) + " MB/S";
    document.getElementById("kpi-download").textContent = data.download.toFixed(2) + " MB/S";
    document.getElementById("kpi-devices").textContent  = data.device_count;
    document.getElementById("kpi-cpu").textContent      = `${Math.round(data.cpu)}% / ${Math.round(data.ram)}%`;

    // 2. Security Status
    const badge = document.getElementById("sec-badge");
    badge.textContent = `SYSTEM: ${data.security.toUpperCase()}`;
    if (data.security.includes("Secure")) {
        badge.style.borderColor = "hsla(150, 100%, 50%, 0.4)";
        badge.style.color = "var(--green)";
    } else if (data.security.includes("Caution")) {
        badge.style.borderColor = "hsla(45, 100%, 50%, 0.4)";
        badge.style.color = "var(--yellow)";
    } else {
        badge.style.borderColor = "hsla(0, 100%, 60%, 0.5)";
        badge.style.color = "var(--red)";
    }

    // 3. Network Chart Update
    netChart.data.datasets[0].data.push(data.upload);
    netChart.data.datasets[0].data.shift();
    netChart.data.datasets[1].data.push(data.download);
    netChart.data.datasets[1].data.shift();
    netChart.update('none'); // Update without full re-animation for performance

    // 4. Device Discovery List
    const deviceList = document.getElementById("device-list");
    if (data.devices && data.devices.length) {
        deviceList.innerHTML = data.devices.map((dev, idx) => `
            <li style="animation-delay: ${idx * 0.1}s">
                <div class="device-info">
                    <span class="device-name">${dev.type}</span>
                    <span class="dev-ip">${dev.ip}</span>
                </div>
                <div class="status-check ${dev.status.includes("Online") ? "status-online" : "status-idle"}">
                    <span class="status-dot">●</span>
                    <span>${dev.status.toUpperCase()}</span>
                </div>
            </li>
        `).join("");
    }

    // 5. AI Alert Feed
    const alertFeed = document.getElementById("alert-feed");
    alertFeed.innerHTML = data.alerts.map(a => `
        <div class="alert-item">
            <strong>[${a.time}]</strong> ${a.msg}
        </div>
    `).join("") || `<div style="color:var(--text-dim); font-size: 0.8rem; text-align: center; padding: 20px;">NOMINAL SYSTEM ACTIVITY</div>`;

    // 6. Network Health
    if (data.network_health) {
        const nh = data.network_health;
        const statusEl = document.getElementById("health-status");
        statusEl.textContent = `STATUS: ${nh.status.toUpperCase()}`;
        statusEl.className = `health-status mode-${nh.status.toLowerCase()}`;

        document.getElementById("health-score").textContent = Math.round(nh.score) + "%";
        document.getElementById("network-load").textContent = Math.round(nh.load) + "%";
        document.getElementById("transfer-delay").textContent = (nh.avg_rtt_ms || 0).toFixed(2) + " ms";

        document.getElementById("health-score-bar").style.width = nh.score + "%";
        document.getElementById("network-load-bar").style.width = nh.load + "%";

        const history = nh.history && nh.history.length ? nh.history : Array(60).fill(nh.score);
        healthChart.data.datasets[0].data = history.slice(-60);
        healthChart.data.labels = Array(healthChart.data.datasets[0].data.length).fill("");

        if (nh.status === "Critical") {
            healthChart.data.datasets[0].borderColor = "var(--red)";
            healthChart.data.datasets[0].backgroundColor = "hsla(0, 100%, 60%, 0.1)";
        } else if (nh.status === "Busy") {
            healthChart.data.datasets[0].borderColor = "var(--yellow)";
            healthChart.data.datasets[0].backgroundColor = "hsla(45, 100%, 50%, 0.1)";
        } else {
            healthChart.data.datasets[0].borderColor = "var(--green)";
            healthChart.data.datasets[0].backgroundColor = "hsla(150, 100%, 50%, 0.1)";
        }
        healthChart.update('none');
    }

    // 7. File Transfers
    const transferList = document.getElementById("transfer-list");
    if (data.transfers && data.transfers.length) {
        transferList.innerHTML = data.transfers.map(t => `
            <div class="transfer-card">
                <div class="tf-name">${t.filename}</div>
                <div class="label-group" style="display:flex; justify-content:space-between; font-size:10px; color:var(--text-dim);">
                    <span>${t.direction} · ${t.mode.toUpperCase()}</span>
                    <span>${(t.size/1024/1024).toFixed(1)} MB</span>
                </div>
                <div style="font-size:0.78rem; color:var(--text-dim);">
                    PEER ${t.addr} · ${t.parallelism} stream(s) · ${t.compression ? "Compressed" : "Raw"} · ${t.encryption ? "AES-GCM" : "Plain"}
                </div>
                <div class="progress-track" style="height: 4px;">
                    <div class="progress-fill" style="width: ${t.progress}%; box-shadow: none;"></div>
                </div>
                <div style="display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; font-size: 0.72rem; color: var(--text-dim);">
                    <div>Throughput: <span style="color:var(--text);">${(t.throughput_mbps || 0).toFixed(2)} MB/s</span></div>
                    <div>Avg RTT: <span style="color:var(--text);">${(t.avg_rtt_ms || 0).toFixed(1)} ms</span></div>
                    <div>Retries: <span style="color:var(--text);">${t.retries || 0}</span></div>
                    <div>Loss Est: <span style="color:var(--text);">${(t.chunk_loss_pct || 0).toFixed(2)}%</span></div>
                    <div>Wire Ratio: <span style="color:var(--text);">${(t.compression_ratio || 1).toFixed(3)}</span></div>
                    <div>Duration: <span style="color:var(--text);">${(t.duration_sec || 0).toFixed(2)} s</span></div>
                </div>
                <div style="font-size: 0.7rem; color: var(--cyan); text-align: right;">${t.status}</div>
            </div>
        `).join("");
    } else {
        transferList.innerHTML = `
            <div class="transfer-card empty-telemetry-card">
                <div class="summary-value">NO ACTIVE SESSIONS</div>
                <div class="dim">Queued, active, and completed sender or receiver sessions will appear here once transfer activity begins.</div>
            </div>
        `;
    }

    const summaryNormal = document.getElementById("summary-normal");
    const summaryParallel = document.getElementById("summary-parallel");
    if (data.transfer_summary) {
        const renderSummary = (item, label) => {
            if (!item || !item.count) {
                const hint = label === "normal"
                    ? "Complete one sequential transfer to populate the baseline."
                    : "Complete one parallel transfer to populate the performance view.";
                return `
                    <div class="summary-state">
                        <div class="summary-value">NO DATA</div>
                        <div class="dim">${hint}</div>
                    </div>
                `;
            }
            return `
                <div style="font-size:0.78rem; color:var(--text-dim); display:grid; gap:6px;">
                    <div>Runs: <span style="color:var(--text);">${item.count}</span></div>
                    <div>Avg throughput: <span style="color:var(--text);">${item.avg_throughput_mbps.toFixed(2)} MB/s</span></div>
                    <div>Avg duration: <span style="color:var(--text);">${item.avg_duration_sec.toFixed(2)} s</span></div>
                    <div>Avg RTT: <span style="color:var(--text);">${item.avg_rtt_ms.toFixed(1)} ms</span></div>
                </div>
            `;
        };
        summaryNormal.innerHTML = renderSummary(data.transfer_summary.normal, "normal");
        summaryParallel.innerHTML = renderSummary(data.transfer_summary.parallel, "parallel");
    }
});

// ── Chat Interaction ───────────────────────────────────────────────────────
async function sendChat() {
    const input = document.getElementById("chat-in");
    const log = document.getElementById("chat-log");
    const query = input.value.trim();
    if (!query) return;

    input.value = "";
    
    // User message
    const userMsg = document.createElement("div");
    userMsg.className = "msg user-msg";
    userMsg.textContent = query;
    log.appendChild(userMsg);
    log.scrollTop = log.scrollHeight;

    try {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query })
        });
        const data = await response.json();
        
        // Bot message
        const botMsg = document.createElement("div");
        botMsg.className = "msg bot-msg";
        botMsg.textContent = data.reply;
        log.appendChild(botMsg);
        log.scrollTop = log.scrollHeight;
    } catch (e) {
        console.error("Chat Error:", e);
    }
}

document.getElementById("chat-in").addEventListener("keypress", (e) => {
    if (e.key === "Enter") sendChat();
});

// ── File Transfer Action ───────────────────────────────────────────────────
async function sendFile() {
    const ip = document.getElementById("ft-ip").value;
    const path = document.getElementById("ft-path").value;
    const mode = document.getElementById("ft-mode").value;
    const parallelism = parseInt(document.getElementById("ft-parallelism").value || "1", 10);
    const chunkSizeKb = parseInt(document.getElementById("ft-chunk").value || "256", 10);
    const maxRetries = parseInt(document.getElementById("ft-retries").value || "3", 10);
    const compression = document.getElementById("ft-compression").checked;
    const encryption = document.getElementById("ft-encryption").checked;
    const feedback = document.getElementById("ft-feedback");
    if (!ip || !path) return alert("System requires both Target IP and Source Path.");
    feedback.className = "status-strip active";
    feedback.textContent = "Queueing transfer session and preparing target handshake...";

    try {
        const res = await fetch("/api/sendfile", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                target_ip: ip,
                file_path: path,
                mode,
                parallelism,
                chunk_size_kb: chunkSizeKb,
                max_retries: maxRetries,
                compression,
                encryption
            })
        });
        const data = await res.json();
        feedback.className = data.ok ? "status-strip active" : "status-strip idle";
        feedback.textContent = data.msg || (data.ok ? "Transfer queued." : "Transfer failed.");
    } catch (e) {
        feedback.className = "status-strip idle";
        feedback.textContent = "Target node unreachable or dispatch setup failed.";
        alert("Transfer failed: target node unreachable.");
    }
}
