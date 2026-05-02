import os
import requests
import json
import threading
import time
import socks
import socket
from flask import Flask
from neonize.client import NewClient
from neonize.events import MessageEv, ConnectedEv
from neonize.utils import log
from neonize.utils.jid import Jid2String
from neonize.utils.enum import ChatPresence, ChatPresenceMedia

# ============================================================
# ⚙️  إعدادات الـ API والـ Web Server
# ============================================================
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "595fa487475d4638adabc1ba0202x5c2.UKts0-LDnqenxbc2iNwZfqki")
OLLAMA_API_URL = (os.environ.get("OLLAMA_API_URL", "https://ollama.com")).strip().rstrip("/") + "/api/chat"
MODEL_NAME = os.environ.get("MODEL_NAME", "gpt-oss:120b-cloud")
PORT = int(os.environ.get("PORT", 7860))

SYSTEM_PROMPT = """أنت مساعد شخصي ذكي. ترد بالعربية بأسلوب ودود وموجز."""
MAX_HISTORY = 10
history_storage = {}

app = Flask(__name__)

@app.route('/')
def home():
    return "WhatsApp Bot is running on Hugging Face! 🚀"

@app.route('/ping')
def ping():
    return "PONG", 200

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# ============================================================
# 🤖 منطق بوت الواتساب
# ============================================================
def get_history(jid):
    if jid not in history_storage:
        history_storage[jid] = [{"role": "system", "content": SYSTEM_PROMPT}]
    return history_storage[jid]

def add_to_history(jid, role, content):
    history = get_history(jid)
    history.append({"role": role, "content": content})
    if len(history) > MAX_HISTORY + 1:
        history.pop(1)

def ask_ollama(jid, user_message):
    add_to_history(jid, "user", user_message)
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {OLLAMA_API_KEY}"}
    payload = {"model": MODEL_NAME, "messages": get_history(jid), "stream": False}
    
    try:
        response = requests.post(OLLAMA_API_URL, headers=headers, json=payload, timeout=60)
        data = response.json()
        reply = data.get("message", {}).get("content") or data.get("choices", [{}])[0].get("message", {}).get("content")
        if reply:
            add_to_history(jid, "assistant", reply)
            return reply
        return "عذراً، لم أتمكن من الرد."
    except Exception as e:
        print(f"❌ API Error: {e}")
        return "حدث خطأ في الاتصال بالسيرفر."

client = NewClient("/home/user/session.db")

@client.event(ConnectedEv)
def on_connected(_client: NewClient, _event: ConnectedEv):
    print("\n[OK] WhatsApp connected!\n")

@client.event(MessageEv)
def on_message(client: NewClient, message: MessageEv):
    message_content = message.Message
    text = message_content.conversation or (message_content.extendedTextMessage.text if message_content.extendedTextMessage else "")
    if message.Info.MessageSource.IsFromMe or not text:
        return
    jid = message.Info.MessageSource.Chat
    client.send_chat_presence(jid, ChatPresence.CHAT_PRESENCE_COMPOSING, ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT)
    reply = ask_ollama(Jid2String(jid), text)
    client.send_message(jid, reply)

# ============================================================
# 🌐 تفعيل بروكسي Tor لتجاوز حجب واتساب
# ============================================================
def setup_tor_proxy():
    """توجيه كل اتصالات الـ socket عبر Tor SOCKS5"""
    print("Setting up Tor SOCKS5 proxy on 127.0.0.1:9050...")
    socks.set_default_proxy(socks.SOCKS5, "127.0.0.1", 9050)
    socket.socket = socks.socksocket
    print("Tor proxy activated!")

def check_tor():
    """التأكد من أن Tor يعمل"""
    for i in range(10):
        try:
            # فحص عبر Tor
            resp = requests.get("https://check.torproject.org/api/ip", timeout=15)
            data = resp.json()
            print(f"Tor Status: IsTor={data.get('IsTor')}, IP={data.get('IP')}")
            return True
        except Exception as e:
            print(f"Waiting for Tor to start... attempt {i+1}/10 ({e})")
            time.sleep(3)
    print("ERROR: Tor failed to start!")
    return False

def run_bot():
    print("Starting WhatsApp Bot...")
    
    # تنظيف البروكسي القديم
    os.environ.pop("http_proxy", None)
    os.environ.pop("https_proxy", None)
    os.environ.pop("HTTP_PROXY", None)
    os.environ.pop("HTTPS_PROXY", None)

    # تفعيل Tor
    setup_tor_proxy()
    
    if check_tor():
        print("Tor is working! Connecting to WhatsApp...")
    else:
        print("WARNING: Tor check failed, trying anyway...")

    # فحص الواتساب عبر Tor
    try:
        print("Testing WhatsApp via Tor...")
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get("https://web.whatsapp.com", headers=headers, timeout=30)
        print(f"WhatsApp via Tor: {res.status_code} OK")
    except Exception as e:
        print(f"WhatsApp via Tor Failed: {e}")

    while True:
        try:
            print("Attempting to connect to WhatsApp via Neonize (through Tor)...")
            client.connect()
            break
        except Exception as e:
            print(f"Connection failed: {e}. Retrying in 20 seconds...")
            time.sleep(20)

if __name__ == "__main__":
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()
    run_bot()
