"""Central controller web dashboard displaying connected worker status and metrics."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Dashboard"])

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NIAT CodePilot - Central Controller Dashboard</title>
    <style>
        :root {
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --bg-card: #1e293b;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --accent-amber: #f59e0b;
            --accent-blue: #3b82f6;
            --border-color: #334155;
        }
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }
        body {
            background-color: var(--bg-primary);
            color: var(--text-primary);
            padding: 24px;
            min-height: 100vh;
        }
        .container {
            max-width: 1280px;
            margin: 0 auto;
        }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 24px;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 28px;
        }
        .header-title h1 {
            font-size: 26px;
            font-weight: 700;
            letter-spacing: -0.5px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .header-title p {
            color: var(--text-secondary);
            font-size: 14px;
            margin-top: 4px;
        }
        .header-actions {
            display: flex;
            align-items: center;
            gap: 16px;
        }
        .badge-live {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(16, 185, 129, 0.15);
            color: var(--accent-green);
            padding: 6px 12px;
            border-radius: 9999px;
            font-size: 12px;
            font-weight: 600;
            border: 1px solid rgba(16, 185, 129, 0.3);
        }
        .pulse-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: var(--accent-green);
            animation: pulse 1.8s infinite;
        }
        @keyframes pulse {
            0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
            70% { transform: scale(1); box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
            100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
        }
        .btn-emergency {
            background-color: var(--accent-red);
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            font-weight: 700;
            font-size: 13px;
            cursor: pointer;
            transition: background 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        .btn-emergency:hover {
            background-color: #dc2626;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 18px;
            margin-bottom: 28px;
        }
        .stat-card {
            background-color: var(--bg-card);
            border: 1px solid var(--border-color);
            padding: 18px 20px;
            border-radius: 10px;
        }
        .stat-card .label {
            font-size: 13px;
            color: var(--text-secondary);
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .stat-card .value {
            font-size: 30px;
            font-weight: 700;
            margin-top: 8px;
        }
        .workers-section {
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.2);
        }
        .section-header {
            padding: 18px 24px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .section-header h2 {
            font-size: 18px;
            font-weight: 600;
        }
        .refresh-info {
            font-size: 12px;
            color: var(--text-secondary);
        }
        .workers-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
            gap: 20px;
            padding: 24px;
        }
        .empty-state {
            grid-column: 1 / -1;
            text-align: center;
            padding: 48px 16px;
            color: var(--text-secondary);
            font-size: 15px;
        }
        .worker-card {
            background-color: #131c2e;
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 14px;
            transition: transform 0.15s, border-color 0.15s;
        }
        .worker-card:hover {
            border-color: #475569;
        }
        .worker-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
        }
        .worker-name {
            font-size: 17px;
            font-weight: 700;
            color: var(--text-primary);
        }
        .worker-id {
            font-size: 12px;
            font-family: monospace;
            color: var(--accent-blue);
            margin-top: 2px;
        }
        .status-pill {
            font-size: 11px;
            font-weight: 700;
            padding: 4px 10px;
            border-radius: 9999px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .status-online {
            background-color: rgba(16, 185, 129, 0.2);
            color: #34d399;
            border: 1px solid #059669;
        }
        .status-offline {
            background-color: rgba(148, 163, 184, 0.15);
            color: #94a3b8;
            border: 1px solid #475569;
        }
        .status-emergency {
            background-color: rgba(239, 68, 68, 0.2);
            color: #f87171;
            border: 1px solid #b91c1c;
        }
        .worker-details {
            font-size: 13px;
            color: var(--text-secondary);
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .detail-row {
            display: flex;
            justify-content: space-between;
        }
        .detail-val {
            font-weight: 500;
            color: var(--text-primary);
            font-family: monospace;
        }
        .permission-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
            font-weight: 600;
            padding: 4px 8px;
            border-radius: 4px;
        }
        .permission-active {
            background: rgba(16, 185, 129, 0.15);
            color: #34d399;
        }
        .permission-inactive {
            background: rgba(148, 163, 184, 0.15);
            color: #94a3b8;
        }
        .metric-bars {
            display: flex;
            flex-direction: column;
            gap: 8px;
            margin-top: 4px;
        }
        .metric-row {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 12px;
        }
        .metric-label {
            width: 45px;
            color: var(--text-secondary);
            font-weight: 600;
        }
        .progress-track {
            flex: 1;
            height: 6px;
            background-color: #334155;
            border-radius: 3px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background-color: var(--accent-blue);
            border-radius: 3px;
            transition: width 0.3s ease;
        }
        .metric-pct {
            width: 40px;
            text-align: right;
            font-family: monospace;
            color: var(--text-secondary);
        }
        .worker-actions {
            margin-top: 6px;
            display: flex;
            justify-content: flex-end;
        }
        .btn-worker-halt {
            background: none;
            border: 1px solid rgba(239, 68, 68, 0.5);
            color: #f87171;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-worker-halt:hover {
            background-color: rgba(239, 68, 68, 0.2);
            border-color: #ef4444;
        }
        footer {
            margin-top: 36px;
            text-align: center;
            font-size: 12px;
            color: #64748b;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="header-title">
                <h1>
                    <span>🛰️</span> NIAT CodePilot Central Controller
                </h1>
                <p>Distributed AI Coding Assistant • 3-Laptop LAN Deployment Dashboard</p>
            </div>
            <div class="header-actions">
                <div class="badge-live">
                    <span class="pulse-dot"></span>
                    <span>LIVE CONTROLLER</span>
                </div>
                <button class="btn-emergency" onclick="triggerGlobalEmergencyStop()">
                    🛑 EMERGENCY STOP ALL
                </button>
            </div>
        </header>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="label">Total Workers</div>
                <div class="value" id="stat-total">0</div>
            </div>
            <div class="stat-card">
                <div class="label">Active Online</div>
                <div class="value" style="color: var(--accent-green);" id="stat-online">0</div>
            </div>
            <div class="stat-card">
                <div class="label">Capture Permitted</div>
                <div class="value" style="color: var(--accent-blue);" id="stat-permitted">0</div>
            </div>
            <div class="stat-card">
                <div class="label">Network Status</div>
                <div class="value" style="font-size: 20px; margin-top: 12px;" id="stat-network">Ready (LAN)</div>
            </div>
        </div>

        <div class="workers-section">
            <div class="section-header">
                <h2>Connected Worker Laptops</h2>
                <div class="refresh-info" id="refresh-time">Connecting to controller...</div>
            </div>
            <div class="workers-grid" id="workers-grid">
                <div class="empty-state">
                    No worker laptops registered yet.<br>
                    Start Worker Alpha (Laptop 2) or Worker Beta (Laptop 3) to see them connect.
                </div>
            </div>
        </div>

        <footer>
            Security Policy: Zero Student Credentials Stored | Explicit Screen Capture Consent Required | Automatic Portal Submissions Prohibited
        </footer>
    </div>

    <script>
        async function fetchWorkers() {
            try {
                const resp = await fetch('/api/v1/workers');
                if (!resp.ok) throw new Error('Failed to fetch worker list');
                const workers = await resp.json();
                renderDashboard(workers);
                document.getElementById('refresh-time').innerText = 'Last updated: ' + new Date().toLocaleTimeString();
            } catch (err) {
                console.error('Error fetching workers:', err);
                document.getElementById('refresh-time').innerText = 'Status: Disconnected or Retrying...';
            }
        }

        function renderDashboard(workers) {
            const total = workers.length;
            const online = workers.filter(w => w.status === 'ONLINE').length;
            const permitted = workers.filter(w => w.permission_active).length;

            document.getElementById('stat-total').innerText = total;
            document.getElementById('stat-online').innerText = online;
            document.getElementById('stat-permitted').innerText = permitted;

            const grid = document.getElementById('workers-grid');
            if (workers.length === 0) {
                grid.innerHTML = `
                    <div class="empty-state">
                        No worker laptops registered yet.<br>
                        Start Worker Alpha (Laptop 2) or Worker Beta (Laptop 3) to see them connect.
                    </div>`;
                return;
            }

            grid.innerHTML = workers.map(w => {
                const statusClass = w.status === 'ONLINE' ? 'status-online' :
                                   w.status === 'EMERGENCY_STOPPED' ? 'status-emergency' : 'status-offline';
                const cpu = w.cpu_percent != null ? Math.round(w.cpu_percent) : 0;
                const mem = w.memory_percent != null ? Math.round(w.memory_percent) : 0;
                
                const lastHb = new Date(w.last_heartbeat);
                const secondsAgo = Math.max(0, Math.round((new Date() - lastHb) / 1000));

                return `
                <div class="worker-card">
                    <div class="worker-header">
                        <div>
                            <div class="worker-name">${escapeHtml(w.worker_name)}</div>
                            <div class="worker-id">${escapeHtml(w.worker_id)}</div>
                        </div>
                        <span class="status-pill ${statusClass}">${w.status}</span>
                    </div>

                    <div class="worker-details">
                        <div class="detail-row">
                            <span>Host & IP:</span>
                            <span class="detail-val">${escapeHtml(w.hostname)} (${escapeHtml(w.ip_address || 'LAN')})</span>
                        </div>
                        <div class="detail-row">
                            <span>Screen Consent:</span>
                            <span class="permission-badge ${w.permission_active ? 'permission-active' : 'permission-inactive'}">
                                ${w.permission_active ? '● Permitted' : '○ Disabled'}
                            </span>
                        </div>
                        <div class="detail-row">
                            <span>Last Heartbeat:</span>
                            <span class="detail-val">${secondsAgo}s ago</span>
                        </div>
                    </div>

                    <div class="metric-bars">
                        <div class="metric-row">
                            <span class="metric-label">CPU</span>
                            <div class="progress-track">
                                <div class="progress-fill" style="width: ${cpu}%"></div>
                            </div>
                            <span class="metric-pct">${cpu}%</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">MEM</span>
                            <div class="progress-track">
                                <div class="progress-fill" style="width: ${mem}%; background-color: var(--accent-amber);"></div>
                            </div>
                            <span class="metric-pct">${mem}%</span>
                        </div>
                    </div>

                    <div class="worker-actions">
                        <button class="btn-worker-halt" onclick="haltWorker('${escapeHtml(w.worker_id)}')">
                            Halt Worker
                        </button>
                    </div>
                </div>
                `;
            }).join('');
        }

        async function haltWorker(workerId) {
            if (!confirm(`Are you sure you want to trigger an Emergency Stop for worker '${workerId}'?`)) {
                return;
            }
            try {
                const resp = await fetch(`/api/v1/workers/${encodeURIComponent(workerId)}/emergency-stop`, {
                    method: 'POST'
                });
                if (resp.ok) {
                    fetchWorkers();
                } else {
                    alert('Failed to trigger emergency stop for worker.');
                }
            } catch (err) {
                alert('Network error: ' + err.message);
            }
        }

        async function triggerGlobalEmergencyStop() {
            if (!confirm('CAUTION: Are you sure you want to trigger an IMMEDIATE EMERGENCY STOP across ALL workers?')) {
                return;
            }
            try {
                const resp = await fetch('/api/v1/workers/emergency-stop', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reason: 'Operator Global Emergency Stop' })
                });
                if (resp.ok) {
                    alert('EMERGENCY STOP dispatched to all connected workers.');
                    fetchWorkers();
                }
            } catch (err) {
                alert('Error sending emergency stop: ' + err.message);
            }
        }

        function escapeHtml(text) {
            if (!text) return '';
            return text.toString()
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }

        // Fetch immediately, then every 2.5s
        fetchWorkers();
        setInterval(fetchWorkers, 2500);
    </script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse, summary="Controller Web Dashboard Root")
@router.get("/dashboard", response_class=HTMLResponse, summary="Controller Web Dashboard")
async def get_dashboard():
    """Render central monitoring dashboard for connected worker laptops."""
    return HTMLResponse(content=DASHBOARD_HTML, status_code=200)
