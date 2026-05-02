import os
import requests
import json
import time
import threading
import sys

# تحميل متغيرات البيئة من ملف .env (للتشغيل المحلي)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from neonize.client import NewClient
from neonize.events import MessageEv, ConnectedEv, QREv
from neonize.utils import log
from neonize.utils.jid import Jid2String
from neonize.utils.enum import ChatPresence, ChatPresenceMedia
import segno

# ============================================================
# ⚙️  إعدادات الـ API
# ============================================================
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
OLLAMA_API_URL = (os.environ.get("OLLAMA_API_URL", "https://ollama.com")).strip().rstrip("/") + "/api/chat"
MODEL_NAME = os.environ.get("MODEL_NAME", "gpt-oss:120b-cloud")

# مدة التشغيل القصوى (5 ساعات و20 دقيقة) عشان GitHub Actions حد أقصى 6 ساعات
MAX_RUNTIME = int(os.environ.get("MAX_RUNTIME", 19200))

SYSTEM_PROMPT = """أنت مساعد شخصي ذكي. ترد بالعربية بأسلوب ودود وموجز."""
MAX_HISTORY = 10
history_storage = {}

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
        if response.status_code != 200:
            print(f"❌ API HTTP {response.status_code}: {response.text[:500]}")
            return f"خطأ من السيرفر (HTTP {response.status_code})"
        data = response.json()
        reply = data.get("message", {}).get("content") or data.get("choices", [{}])[0].get("message", {}).get("content")
        if reply:
            add_to_history(jid, "assistant", reply)
            return reply
        print(f"❌ Unexpected API response: {json.dumps(data)[:500]}")
        return "عذراً، لم أتمكن من الرد."
    except Exception as e:
        print(f"❌ API Error: {type(e).__name__}: {e}")
        return "حدث خطأ في الاتصال بالسيرفر."

client = NewClient("session.db")
qr_shown = False

@client.event(QREv)
def on_qr(_client: NewClient, event: QREv):
    global qr_shown
    if not qr_shown:
        qr_shown = True
        codes = event.Codes
        if codes:
            qr_code = segno.make(codes[0])
            qr_code.terminal(compact=True)
            print("\n📱 Scan this QR code with WhatsApp (Linked Devices)")
            print("⏳ Waiting for scan...\n")
    else:
        print("⏳ Still waiting for QR scan...")

@client.event(ConnectedEv)
def on_connected(_client: NewClient, _event: ConnectedEv):
    print("\n✅ WhatsApp connected successfully!\n")

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
# ⏱️ مؤقت الإيقاف التلقائي (لـ GitHub Actions)
# ============================================================
def shutdown_timer():
    """إيقاف البوت قبل حد الـ 6 ساعات في GitHub Actions"""
    print(f"⏱️ Auto-shutdown timer set: {MAX_RUNTIME} seconds ({MAX_RUNTIME//3600}h {(MAX_RUNTIME%3600)//60}m)")
    time.sleep(MAX_RUNTIME)
    print("⏱️ Scheduled shutdown - session saved automatically.")
    os._exit(0)

if __name__ == "__main__":
    print("🤖 Starting WhatsApp Bot...")
    print(f"🔗 API URL: {OLLAMA_API_URL}")
    print(f"🔑 API Key: {'✅ Set' if OLLAMA_API_KEY else '❌ MISSING!'}")
    print(f"🧠 Model: {MODEL_NAME}")
    
    if not OLLAMA_API_KEY:
        print("⚠️  WARNING: OLLAMA_API_KEY is not set! Create a .env file with your keys.")
    
    # تشغيل مؤقت الإيقاف
    timer = threading.Thread(target=shutdown_timer, daemon=True)
    timer.start()

    while True:
        try:
            client.connect()
            break
        except Exception as e:
            print(f"Connection failed: {e}. Retrying in 10 seconds...")
            time.sleep(10)

