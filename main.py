import os
import requests
import json
import time
import threading
import sys
from neonize.client import NewClient
from neonize.events import MessageEv, ConnectedEv
from neonize.utils import log
from neonize.utils.jid import Jid2String
from neonize.utils.enum import ChatPresence, ChatPresenceMedia

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
        data = response.json()
        reply = data.get("message", {}).get("content") or data.get("choices", [{}])[0].get("message", {}).get("content")
        if reply:
            add_to_history(jid, "assistant", reply)
            return reply
        return "عذراً، لم أتمكن من الرد."
    except Exception as e:
        print(f"❌ API Error: {e}")
        return "حدث خطأ في الاتصال بالسيرفر."

client = NewClient("session.db")

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
