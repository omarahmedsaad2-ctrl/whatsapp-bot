import os
import sys
import io
import re
import json
import time
import threading
import requests
import psycopg2
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# Fix Windows encoding BEFORE any library imports
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from neonize.client import NewClient
from neonize.events import MessageEv, ConnectedEv
from neonize.utils.jid import Jid2String, String2Jid
from neonize.utils.enum import ChatPresence, ChatPresenceMedia
import segno

CAIRO_TZ = ZoneInfo("Africa/Cairo")

OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "").strip()
api_url_env = os.environ.get("OLLAMA_API_URL", "https://ollama.com").strip()
OLLAMA_API_URL = api_url_env.rstrip("/")
OLLAMA_MODEL = os.environ.get("MODEL_NAME", "gpt-oss:120b-cloud").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
MAX_RUNTIME = int(os.environ.get("MAX_RUNTIME", 19200))

SYSTEM_PROMPT = (
    "You are Gen Code AI Assistant by Gen Code Software. Chatting on WhatsApp.\n"
    "When asked to introduce yourself or what you can do, emphasize your capabilities confidently and clearly. State that you are an advanced AI assistant capable of:\n"
    "- Smart Scheduling: Managing and sending natural language reminders at any time.\n"
    "- Continuous Learning: Automatically remembering user preferences, facts, and ongoing tasks to provide highly personalized interactions over time.\n"
    "- Contextual Memory: Maintaining deep context across long conversations.\n"
    "- Proactive Follow-ups: Reaching out autonomously to check on tasks or ongoing discussions.\n"
    "- Answering complex queries and providing insightful advice in clear, concise language.\n"
    "Rules:\n"
    "- Language: Only Egyptian Arabic or English based on user input. No MSA/Fusha.\n"
    "- Context: Use provided knowledge naturally without citing 'knowledge base'.\n"
    "- Auto-Memory: If the user reveals a personal preference, fact, or ongoing task, save it silently by including `<LEARN>the fact</LEARN>` anywhere in your response. (e.g. `<LEARN>User works as a Python Developer</LEARN>`).\n"
    "- No Internal Monologue: Do not describe your thought process. Give the final answer directly.\n"
    "- Honesty: Say if you don't know.\n"
    "- No Fake Tools: NEVER output `<FunctionCall>`, XML tool tags, or pretend to call APIs. You do not have internet access or external tools.\n"
    "- Unspecified Reminder Times: If the user asks for a reminder but does not specify an exact time (e.g., 'remind me at Friday prayer'), politely ask them to specify the exact time they want the reminder for.\n"
    "- ABSOLUTELY NO CODE: NEVER output any code, code blocks, code snippets, programming examples, or technical syntax in your responses. This is strictly forbidden. If the user asks for code, explain concepts in plain words only.\n"
    "- REMINDER MANAGEMENT: The user DOES NOT use commands (like /delete). If they ask to show reminders, delete a reminder, or clear them, act conversationally but output the appropriate intent JSON when parsing.\n"
    "<Style>\n"
    "- Clear, simple, spartan, informative.\n"
    "- Short, impactful sentences. Active voice. Practical insights. Use data/examples.\n"
    "- Direct address: use 'you'/'your'.\n"
    "- NO markdown, NO asterisks, NO hashtags, NO semicolons, NO em-dashes (use periods/commas).\n"
    "- NO warnings, notes, adjectives, adverbs, metaphors, cliches, generalizations, setup language, rhetorical questions.\n"
    "- FORBIDDEN WORDS: can, may, just, that, very, really, literally, actually, certainly, probably, basically, could, maybe, delve, embark, enlightening, ever, insight, unwavering, robust, imagine, within, diverse, commendable, swift, virtual, realm, however, harness, exciting, groundbreaking, cutting-edge, remarkable, it, remains to be seen, glimpse into, navigating, landscape, stark, testament, in summary, in conclusion, moreover, boost, skyrocketing, opened up, powerful, inquiries, ever-evolving.\n"
    "</Style>\n"
    "CRITICAL: Review output before replying to ensure strict style, NO CODE, and NO FAKE TOOLS."
)

client = NewClient("session.db")
_qr_count = 0
_last_qr_time = 0

# ============================================================
# 🗄️ Database Logic (PostgreSQL)
# ============================================================
DB_INITIALIZED = False

def get_db_connection():
    if not DATABASE_URL:
        return None, "DATABASE_URL is empty or not set."
    try:
        url = DATABASE_URL
        if "supabase.co" in url or "pooler.supabase.com" in url:
            if "sslmode=" not in url:
                separator = "&" if "?" in url else "?"
                url += f"{separator}sslmode=require"
        conn = psycopg2.connect(url, connect_timeout=10)
        return conn, None
    except Exception as e:
        return None, str(e)

def init_db():
    conn, err = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS wa_messages (
                        id SERIAL PRIMARY KEY,
                        jid TEXT,
                        role TEXT,
                        content TEXT,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_wa_messages_jid ON wa_messages(jid);
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS wa_knowledge (
                        id SERIAL PRIMARY KEY,
                        content TEXT NOT NULL,
                        search_vector tsvector,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_wa_knowledge_search ON wa_knowledge USING GIN(search_vector);
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS wa_reminders (
                        id SERIAL PRIMARY KEY,
                        jid TEXT,
                        message TEXT,
                        remind_at TIMESTAMP WITH TIME ZONE,
                        is_sent BOOLEAN DEFAULT false,
                        frequency TEXT DEFAULT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                conn.commit()
        except Exception as e:
            print(f"[DB] Error initializing DB: {e}")
        finally:
            conn.close()
    else:
        print(f"[DB] Could not connect: {err}")

def ensure_db_initialized():
    global DB_INITIALIZED
    if not DB_INITIALIZED and DATABASE_URL:
        init_db()
        DB_INITIALIZED = True

def save_message(jid, role, content):
    conn, _ = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO wa_messages (jid, role, content) VALUES (%s, %s, %s)", (jid, role, content))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

def _has_arabic(text):
    return bool(re.search(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]', text))

def knowledge_search(query_text, limit=3):
    conn, _ = get_db_connection()
    results = []
    if conn:
        try:
            with conn.cursor() as cur:
                ts_config = 'simple' if _has_arabic(query_text) else 'english'
                cur.execute(
                    f"""
                    SELECT content, ts_rank(search_vector, plainto_tsquery('{ts_config}', %s)) as rank
                    FROM wa_knowledge 
                    WHERE search_vector @@ plainto_tsquery('{ts_config}', %s)
                    ORDER BY rank DESC LIMIT %s
                    """,
                    (query_text, query_text, limit)
                )
                results = [row[0] for row in cur.fetchall()]
                if not results:
                    words = [w for w in query_text.split() if len(w) > 2][:4]
                    if words:
                        like_conditions = " OR ".join(["content ILIKE %s"] * len(words))
                        like_params = [f"%{w}%" for w in words] + [limit]
                        cur.execute(f"SELECT content FROM wa_knowledge WHERE {like_conditions} LIMIT %s", like_params)
                        results = [row[0] for row in cur.fetchall()]
        except Exception:
            pass
        finally:
            conn.close()
    if results:
        context = "\n---\n".join(results)
        return f"\nRelevant Context found in my knowledge base:\n{context}\n"
    return ""

def save_to_knowledge(text):
    conn, _ = get_db_connection()
    if conn:
        try:
            ts_config = 'simple' if _has_arabic(text) else 'english'
            with conn.cursor() as cur:
                cur.execute(f"INSERT INTO wa_knowledge (content, search_vector) VALUES (%s, to_tsvector('{ts_config}', %s))", (text, text))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

def summarize_text(prompt):
    headers = {"Authorization": f"Bearer {OLLAMA_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": OLLAMA_MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False}
    try:
        resp = requests.post(f"{OLLAMA_API_URL}/api/chat", json=payload, headers=headers, timeout=60)
        if resp.status_code == 200:
            return resp.json().get("message", {}).get("content", "")
    except Exception:
        pass
    return "⚠️ Error"

def compact_user_history(jid):
    conn, _ = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, role, content FROM wa_messages WHERE jid = %s ORDER BY created_at ASC", (jid,))
            rows = cur.fetchall()
            if len(rows) > 60:
                old_messages = rows[:-20]
                recent_messages = rows[-20:]
                old_text = "".join([f"{'User' if m[1]=='user' else 'AI'}: {m[2]}\n" for m in old_messages])
                prompt = (
                    "Please provide a concise summary of the following conversation history. "
                    "Focus on the main topics discussed, user preferences, and any important ongoing context. "
                    "Do NOT include conversational filler. Keep it informative and brief.\n\n"
                    f"{old_text}"
                )
                summary = summarize_text(prompt)
                if summary and not summary.startswith("⚠️"):
                    old_ids = tuple(m[0] for m in old_messages)
                    cur.execute("DELETE FROM wa_messages WHERE id IN %s", (old_ids,))
                    cur.execute(
                        "INSERT INTO wa_messages (jid, role, content, created_at) "
                        "VALUES (%s, 'system', %s, (SELECT created_at FROM wa_messages WHERE id = %s) - INTERVAL '1 second')",
                        (jid, f"[Context Compaction Summary of previous {len(old_messages)} messages]:\n{summary}", recent_messages[0][0])
                    )
                    conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

def get_chat_history(jid, limit=100):
    conn, _ = get_db_connection()
    history = []
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT role, content FROM (
                        SELECT role, content, created_at FROM wa_messages WHERE jid = %s ORDER BY created_at DESC LIMIT %s
                    ) sub ORDER BY created_at ASC;
                    """,
                    (jid, limit)
                )
                history = [{"role": row[0], "content": row[1]} for row in cur.fetchall()]
        except Exception:
            pass
        finally:
            conn.close()
    return history

def add_reminder(jid, message, remind_at_iso, frequency=None):
    conn, _ = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO wa_reminders (jid, message, remind_at, is_sent, frequency) VALUES (%s, %s, %s, false, %s) RETURNING id",
                    (jid, message, remind_at_iso, frequency)
                )
                rem_id = cur.fetchone()[0]
            conn.commit()
            return True, rem_id
        except Exception:
            pass
        finally:
            conn.close()
    return False, None

def list_user_reminders(jid):
    conn, _ = get_db_connection()
    reminders = []
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, message, remind_at, is_sent FROM wa_reminders WHERE jid = %s ORDER BY remind_at DESC LIMIT 20", (jid,))
                reminders = cur.fetchall()
        except Exception:
            pass
        finally:
            conn.close()
    return reminders

def delete_user_reminder(jid, reminder_id):
    conn, _ = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM wa_reminders WHERE id = %s AND jid = %s", (reminder_id, jid))
                deleted = cur.rowcount
            conn.commit()
            return deleted > 0
        except Exception:
            pass
        finally:
            conn.close()
    return False

def clear_user_reminders(jid):
    conn, _ = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM wa_reminders WHERE jid = %s", (jid,))
                deleted = cur.rowcount
            conn.commit()
            return True, deleted
        except Exception:
            pass
        finally:
            conn.close()
    return False, 0

def _format_cairo_time(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        cairo_dt = dt.astimezone(CAIRO_TZ)
        day_names = {0: "الاتنين", 1: "الثلاثاء", 2: "الأربعاء", 3: "الخميس", 4: "الجمعة", 5: "السبت", 6: "الأحد"}
        month_names = {1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل", 5: "مايو", 6: "يونيو", 7: "يوليو", 8: "أغسطس", 9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر"}
        day_name = day_names.get(cairo_dt.weekday(), "")
        month_name = month_names.get(cairo_dt.month, "")
        period = "صباحا" if cairo_dt.hour < 12 else "مساء"
        hour_12 = cairo_dt.hour % 12 or 12
        return f"{day_name} {cairo_dt.day} {month_name} {cairo_dt.year} - {hour_12}:{cairo_dt.strftime('%M')} {period}"
    except Exception:
        return iso_str

def _send_wa_message(jid, text):
    try:
        jid_obj = String2Jid(jid) if isinstance(jid, str) else jid
        client.send_message(jid_obj, text)
    except Exception as e:
        print(f"[ERR] Failed to send to {jid}: {e}")

# ============================================================
# 🧠 AI Query & Parsing
# ============================================================

def try_parse_reminder(jid, text, history=None):
    now_local = datetime.now(CAIRO_TZ)
    now_str = now_local.isoformat()
    system_p = (
        f"You are an intent parser. The user's local time (UTC+3) is {now_str}. "
        "Determine the user's intent from the text. Return ONLY a valid JSON object matching one of these intents:\n"
        "1. Set a ONE-TIME reminder: {\"intent\": \"add_reminder\", \"message\": \"what to remind\", \"remind_at\": \"2026-05-01T15:00:00+03:00\", \"recurring\": false}\n"
        "2. Set a RECURRING reminder (daily/weekly/etc): {\"intent\": \"add_reminder\", \"message\": \"what to remind\", \"remind_at\": \"2026-05-01T08:00:00+03:00\", \"recurring\": true, \"frequency\": \"daily\"}\n"
        "   frequency options: daily, weekly, monthly, weekdays, weekends\n"
        "3. Clear/Delete ALL reminders: {\"intent\": \"clear_reminders\"}\n"
        "4. Delete a specific reminder: {\"intent\": \"delete_reminder\", \"id\": 5} (only if they mention a specific ID)\n"
        "5. Show/List all reminders: {\"intent\": \"list_reminders\"}\n"
        "6. Normal chat / ask a question / anything else: {\"intent\": \"chat\"}\n"
        "RULES:\n"
        "- Parse Egyptian Arabic naturally. 'كمان ساعة' = 1 hour from now. 'بكره' = tomorrow. 'كل يوم' = daily recurring.\n"
        "- 'فكرني' or 'ذكرني' or 'نبهني' or 'reminder' = add_reminder intent.\n"
        "- If user says 'كل يوم' or 'يوميا' or 'كل اسبوع' = recurring.\n"
        "- 'امسح كل التذكيرات' or 'شيل التذكيرات كلها' = clear_reminders.\n"
        "- 'عرض التذكيرات' or 'ايه التذكيرات' = list_reminders.\n"
        "- If text relies on context, use provided history to resolve it.\n"
        "- Do NOT write code or explanations. Output ONLY the JSON object."
    )
    headers = {"Authorization": f"Bearer {OLLAMA_API_KEY}", "Content-Type": "application/json"}
    messages = [{"role": "system", "content": system_p}]
    if history: messages.extend(history)
    messages.append({"role": "user", "content": text})
    payload = {"model": OLLAMA_MODEL, "messages": messages, "stream": False, "format": "json"}
    try:
        resp = requests.post(f"{OLLAMA_API_URL}/api/chat", json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            content = resp.json().get("message", {}).get("content", "")
            try:
                data = json.loads(content)
                intent = data.get("intent", "chat")
                
                if intent == "add_reminder" and data.get("message") and data.get("remind_at"):
                    freq = data.get("frequency") if data.get("recurring") else None
                    success, r_id = add_reminder(jid, data["message"], data["remind_at"], freq)
                    if success:
                        freq_map = {"daily": "يوميا", "weekly": "أسبوعيا", "monthly": "شهريا", "weekdays": "أيام الشغل", "weekends": "الويكند"}
                        freq_text = f"\n🔄 تكرار: {freq_map.get(freq, freq)}" if freq else ""
                        nice_time = _format_cairo_time(data['remind_at'])
                        _send_wa_message(jid, f"✅ تم حفظ التذكير!\n\n📌 هفكرك بـ: {data['message']}\n📅 الموعد: {nice_time}{freq_text}")
                    return True
                
                elif intent == "clear_reminders":
                    success, deleted = clear_user_reminders(jid)
                    _send_wa_message(jid, f"✅ تم مسح جميع التذكيرات ({deleted} تذكير)." if success else "❌ حدث خطأ.")
                    return True
                
                elif intent == "delete_reminder" and data.get("id"):
                    r_id = data.get("id")
                    if delete_user_reminder(jid, r_id):
                        _send_wa_message(jid, f"🗑️ تم حذف التذكير رقم {r_id} بنجاح!")
                    else:
                        _send_wa_message(jid, "❌ مفيش تذكير بالرقم ده أو تم حذفه مسبقا.")
                    return True
                    
                elif intent == "list_reminders":
                    reminders = list_user_reminders(jid)
                    if not reminders:
                        _send_wa_message(jid, "⏰ معندكش أي تذكيرات دلوقتي.\nقولي مثلا: 'فكرني كمان ساعة بالشغل'")
                        return True
                    lines = ["⏰ تذكيراتك:\n"]
                    for r_id, msg, r_time, is_sent in reminders:
                        if r_time:
                            if r_time.tzinfo is None: r_time = r_time.replace(tzinfo=timezone.utc)
                            local_time = r_time.astimezone(CAIRO_TZ)
                        else:
                            local_time = None
                        t_str = local_time.strftime("%Y-%m-%d %I:%M %p") if local_time else str(r_time)
                        status = "✅ تم" if is_sent else "⏳ قادم"
                        lines.append(f"🔹 [{r_id}] {msg}\n   └ 📅 {t_str} | {status}")
                    lines.append("\n🗑️ لحذف تذكير قولي: 'امسح التذكير رقم كذا'")
                    _send_wa_message(jid, "\n".join(lines))
                    return True
            except json.JSONDecodeError: pass
    except Exception: pass
    return False

def query_ollama(history):
    headers = {"Authorization": f"Bearer {OLLAMA_API_KEY}", "Content-Type": "application/json"}
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    payload = {"model": OLLAMA_MODEL, "messages": messages, "stream": False}
    try:
        resp = requests.post(f"{OLLAMA_API_URL}/api/chat", json=payload, headers=headers, timeout=60)
        if resp.status_code == 200:
            return resp.json().get("message", {}).get("content", "")
    except Exception: pass
    return "عذرا، لم أتمكن من الرد الآن."

# ============================================================
# 🔄 Cron & Autonomous Check
# ============================================================

def process_due_reminders():
    conn, _ = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, jid, message, frequency FROM wa_reminders WHERE remind_at <= NOW() AND is_sent = false")
                due_reminders = cur.fetchall()
                for row in due_reminders:
                    r_id, jid, msg, freq = row[0], row[1], row[2], row[3]
                    _send_wa_message(jid, f"⏰ تذكير: {msg}")
                    if freq and freq in ('daily', 'weekly', 'monthly', 'weekdays', 'weekends'):
                        interval_map = {'daily': '1 day', 'weekly': '7 days', 'monthly': '1 month', 'weekdays': '1 day', 'weekends': '1 day'}
                        cur.execute(f"UPDATE wa_reminders SET remind_at = remind_at + INTERVAL '{interval_map[freq]}', is_sent = false WHERE id = %s", (r_id,))
                    else:
                        cur.execute("UPDATE wa_reminders SET is_sent = true WHERE id = %s", (r_id,))
                conn.commit()
        except Exception as e: print(f"[CRON ERR] {e}")
        finally: conn.close()

def process_autonomous_loop():
    conn, _ = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT jid FROM wa_messages 
                GROUP BY jid 
                HAVING EXTRACT(EPOCH FROM (NOW() - MAX(created_at))) / 3600 BETWEEN 23.5 AND 24.5
            """)
            users = cur.fetchall()
            for row in users:
                jid = row[0]
                history = get_chat_history(jid, limit=20)
                if not history: continue
                prompt = (
                    "It has been 24 hours since your last conversation. Review the recent history and decide if you should proactively follow up on an ongoing topic. "
                    "If you have something natural to say, write the message. If nothing specific, output exactly 'EMPTY'."
                )
                messages_for_ai = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [{"role": "user", "content": prompt}]
                headers = {"Authorization": f"Bearer {OLLAMA_API_KEY}", "Content-Type": "application/json"}
                payload = {"model": OLLAMA_MODEL, "messages": messages_for_ai, "stream": False}
                resp = requests.post(f"{OLLAMA_API_URL}/api/chat", json=payload, headers=headers, timeout=60)
                if resp.status_code == 200:
                    ai_reply = resp.json().get("message", {}).get("content", "").strip()
                    if ai_reply and ai_reply.upper() != "EMPTY" and not ai_reply.startswith("<LEARN>"):
                        clean_ai_reply = re.sub(r'<LEARN>.*?</LEARN>', '', ai_reply, flags=re.IGNORECASE | re.DOTALL).strip()
                        if clean_ai_reply:
                            _send_wa_message(jid, clean_ai_reply)
                            save_message(jid, "assistant", clean_ai_reply)
                    else:
                        save_message(jid, "system", "[Autonomous Check: Skipped]")
    except Exception as e: print(f"[AUTO ERR] {e}")
    finally: conn.close()

def background_tasks():
    ensure_db_initialized()
    while True:
        try:
            process_due_reminders()
            process_autonomous_loop()
        except Exception as e:
            print(f"[BG TASK ERR] {e}")
        time.sleep(60) # Run every minute

# ============================================================
# 🟢 Neonize Handlers
# ============================================================

@client.event.qr
def on_qr(_client: NewClient, data_qr: bytes):
    """عرض QR code واحد بس - مع debounce 20 ثانية"""
    global _qr_count, _last_qr_time
    now = time.time()
    if now - _last_qr_time < 20: return
    _last_qr_time = now
    _qr_count += 1
    if _qr_count > 1:
        print("\n" + "=" * 50 + "\n>> QR expired - new one below:\n" + "=" * 50)
    else:
        print("\n" + "=" * 50)
    qr_code = segno.make(data_qr)
    qr_code.terminal(compact=True)
    print(f"\n>> Scan with WhatsApp > Linked Devices > Link a Device")
    print(f">> Attempt #{_qr_count}\n>> Waiting for scan...\n")

@client.event(ConnectedEv)
def on_connected(_client: NewClient, _event: ConnectedEv):
    global _qr_count
    _qr_count = 0
    print("\n" + "=" * 50 + "\n[OK] WhatsApp connected successfully!\n" + "=" * 50 + "\n")

@client.event(MessageEv)
def on_message(client: NewClient, message: MessageEv):
    try:
        message_content = message.Message
        text = message_content.conversation or (message_content.extendedTextMessage.text if message_content.extendedTextMessage else "")
        if message.Info.MessageSource.IsFromMe or not text: return

        jid_obj = message.Info.MessageSource.Chat
        sender = Jid2String(jid_obj)
        print(f"[MSG] From {sender}: {text[:80]}...")

        ensure_db_initialized()
        client.send_chat_presence(jid_obj, ChatPresence.CHAT_PRESENCE_COMPOSING, ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT)

        # 1. Compact history if too long
        compact_user_history(sender)

        # 2. Get history from DB
        history = get_chat_history(sender, limit=100)

        # 3. Check for reminders via NLP intent
        is_reminder = try_parse_reminder(sender, text, history[-4:])
        if is_reminder:
            save_message(sender, "user", text)
            print(f"[OK] Handled as reminder/intent for {sender}")
            return

        # 4. Save user message for normal chat
        save_message(sender, "user", text)

        # 5. Search knowledge base
        context = knowledge_search(text)
        text_with_context = f"Context from my knowledge base: {context}\n\nUser Question: {text}" if context else text

        # 6. Query AI
        ai_response = query_ollama(history + [{"role": "user", "content": text_with_context}])

        # 7. Process Auto-Memory tags
        learn_matches = re.findall(r'<LEARN>(.*?)</LEARN>', ai_response, flags=re.IGNORECASE | re.DOTALL)
        for fact in learn_matches:
            save_to_knowledge(fact.strip())

        # Clean tags
        clean_ai_response = re.sub(r'<LEARN>.*?</LEARN>', '', ai_response, flags=re.IGNORECASE | re.DOTALL)
        clean_ai_response = re.sub(r'<FunctionCall>.*?</FunctionCall>', '', clean_ai_response, flags=re.IGNORECASE | re.DOTALL).strip()

        if not clean_ai_response and learn_matches:
            clean_ai_response = "👍 تمام حفظتها"
        elif not clean_ai_response:
            clean_ai_response = "عذرا، لم أتمكن من الرد."

        # 8. Save assistant response and send
        save_message(sender, "assistant", clean_ai_response)
        client.send_message(jid_obj, clean_ai_response)
        print(f"[OK] Reply sent to {sender}")

    except Exception as e:
        print(f"[ERR] Error processing message: {type(e).__name__}: {e}")

# ============================================================
# ⏱️ مؤقت الإيقاف التلقائي
# ============================================================
def shutdown_timer():
    print(f"[TIMER] Auto-shutdown: {MAX_RUNTIME}s ({MAX_RUNTIME//3600}h {(MAX_RUNTIME%3600)//60}m)")
    time.sleep(MAX_RUNTIME)
    print("[TIMER] Scheduled shutdown - session saved.")
    os._exit(0)

if __name__ == "__main__":
    print("[BOT] Starting WhatsApp Bot...")
    print(f"[URL] {OLLAMA_API_URL}")
    print(f"[KEY] {'Set' if OLLAMA_API_KEY else 'MISSING!'}")
    print(f"[MDL] {OLLAMA_MODEL}")
    print(f"[DB] {'Set' if DATABASE_URL else 'MISSING!'}")

    if not OLLAMA_API_KEY:
        print("[WARN] OLLAMA_API_KEY is not set!")

    timer = threading.Thread(target=shutdown_timer, daemon=True)
    timer.start()

    bg_thread = threading.Thread(target=background_tasks, daemon=True)
    bg_thread.start()

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
