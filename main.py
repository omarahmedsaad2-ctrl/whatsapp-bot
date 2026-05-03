import os
import sys
import io

# Fix Windows encoding BEFORE any library imports
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

import requests
import json
import time
import threading

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
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "").strip()
api_url_env = os.environ.get("OLLAMA_API_URL", "").strip()
if not api_url_env:
    api_url_env = "https://ollama.com"
OLLAMA_API_URL = api_url_env.rstrip("/") + "/api/chat"
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
_qr_count = 0
_last_qr_time = 0

@client.event.qr
def on_qr(_client: NewClient, data_qr: bytes):
    """عرض QR code واحد بس - مع debounce 20 ثانية"""
    global _qr_count, _last_qr_time
    now = time.time()

    # Debounce: تجاهل QR events لو مر أقل من 20 ثانية
    if now - _last_qr_time < 20:
        return

    _last_qr_time = now
    _qr_count += 1

    if _qr_count > 1:
        print("\n" + "=" * 50)
        print(">> QR expired - new one below:")
        print("=" * 50)
    else:
        print("\n" + "=" * 50)

    qr_code = segno.make(data_qr)
    qr_code.terminal(compact=True)
    print(f"\n>> Scan with WhatsApp > Linked Devices > Link a Device")
    print(f">> Attempt #{_qr_count}")
    print(">> Waiting for scan...\n")

@client.event(ConnectedEv)
def on_connected(_client: NewClient, _event: ConnectedEv):
    global _qr_count
    _qr_count = 0
    print("\n" + "=" * 50)
    print("[OK] WhatsApp connected successfully!")
    print("=" * 50 + "\n")

@client.event(MessageEv)
def on_message(client: NewClient, message: MessageEv):
    try:
        message_content = message.Message
        text = message_content.conversation or (
            message_content.extendedTextMessage.text
            if message_content.extendedTextMessage
            else ""
        )
        if message.Info.MessageSource.IsFromMe or not text:
            return

        jid = message.Info.MessageSource.Chat
        sender = Jid2String(jid)
        print(f"[MSG] From {sender}: {text[:80]}...")

        client.send_chat_presence(
            jid,
            ChatPresence.CHAT_PRESENCE_COMPOSING,
            ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT,
        )
        reply = ask_ollama(sender, text)
        client.send_message(jid, reply)
        print(f"[OK] Reply sent to {sender}")
    except Exception as e:
        print(f"[ERR] Error processing message: {type(e).__name__}: {e}")

# ============================================================
# ⏱️ مؤقت الإيقاف التلقائي (لـ GitHub Actions)
# ============================================================
def shutdown_timer():
    """إيقاف البوت قبل حد الـ 6 ساعات في GitHub Actions"""
    print(f"[TIMER] Auto-shutdown: {MAX_RUNTIME}s ({MAX_RUNTIME//3600}h {(MAX_RUNTIME%3600)//60}m)")
    time.sleep(MAX_RUNTIME)
    print("[TIMER] Scheduled shutdown - session saved.")
    os._exit(0)

if __name__ == "__main__":
    print("[BOT] Starting WhatsApp Bot...")
    print(f"[URL] {OLLAMA_API_URL}")
    print(f"[KEY] {'Set' if OLLAMA_API_KEY else 'MISSING!'}")
    print(f"[MDL] {MODEL_NAME}")

    if not OLLAMA_API_KEY:
        print("[WARN] OLLAMA_API_KEY is not set! Create a .env file.")

    # تشغيل مؤقت الإيقاف
    timer = threading.Thread(target=shutdown_timer, daemon=True)
    timer.start()

    # حذف الـ session القديم لو فيه مشكلة
    if os.path.exists("session.db") and os.path.getsize("session.db") > 0:
        print("[INFO] Found existing session, reconnecting...")
    else:
        print("[INFO] No session found, will show QR code...")

    try:
        client.connect()
    except KeyboardInterrupt:
        print("\n[BYE] Bot stopped by user.")
    except Exception as e:
        print(f"[FATAL] {type(e).__name__}: {e}")
        sys.exit(1)
