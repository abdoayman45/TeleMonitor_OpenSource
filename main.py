#pyinstaller --onefile --name="Telegram Monitor App" --icon="the_icon_app.ico" --windowed main.py


import os
import json
import re
import sqlite3
import threading
import queue
import tkinter as tk
import asyncio
import webbrowser
from tkinter import scrolledtext, messagebox, ttk
from collections import deque
from time import time, strftime, localtime
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import User, Channel
from cryptography.fernet import Fernet
from dotenv import load_dotenv


# تحميل المتغيرات البيئية أولاً (يمكن تركها فارغة لأن بيانات العميل تُدخل يدويًا)
load_dotenv()

# ثابت لتشفير وفك تشفير توكن البوت (يجب عدم تغييره)

fernet = Fernet(os.getenv("BOT_ENCRYPTION_KEY"))
# --- إعدادات التشفير والتكوين ---
# هنا يتم تخزين توكن البوت مشفرًا، بحيث لا يظهر صريحاً في الكود.
DEFAULT_CONFIG = {
    "keywords": [],
    "stickers": [],
    "API_ID": "",
    "API_HASH": "",
    "user_id": "",
    "BOT_TOKEN": "gAAAAABnoR3JQkhVjxPCEiRO3bKAeylWN0nFlpb8CIT8xlTXRboztdvpiG4DadXqje_i1Kx3pIrU598Y2djyRhWO-kqR0IGeVP5JSyXEZJV_46rFxD4553u-SDy4MV-3rcmxgAgbWMP5"
}
CONFIG_FILE = "config.json"  # اسم ملف التخزين
ENCRYPTION_KEY_FILE = ".key"  # ملف تخزين مفتاح التشفير

class SecureConfigManager:
    def __init__(self):
        self.key = self._get_encryption_key()
        self.cipher = Fernet(self.key)

    def _get_encryption_key(self):
        if os.path.exists(ENCRYPTION_KEY_FILE):
            with open(ENCRYPTION_KEY_FILE, "rb") as key_file:
                return key_file.read()
        new_key = Fernet.generate_key()
        with open(ENCRYPTION_KEY_FILE, "wb") as key_file:
            key_file.write(new_key)
        os.chmod(ENCRYPTION_KEY_FILE, 0o600)
        return new_key

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "rb") as f:
                    encrypted = f.read()
                    return json.loads(self.cipher.decrypt(encrypted).decode())
            except Exception as e:
                print(f"Error loading config: {e}")
                return DEFAULT_CONFIG.copy()
        return DEFAULT_CONFIG.copy()

    def save_config(self, config):
        encrypted = self.cipher.encrypt(json.dumps(config).encode())
        with open(CONFIG_FILE, "wb") as f:
            f.write(encrypted)

# إعداد قاعدة البيانات (SQLite) بطريقة آمنة
class SentMessageDB:
    def __init__(self):
        self._initialize_db()

    def _initialize_db(self):
        with self._get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sent_messages (
                    message_id INTEGER PRIMARY KEY,
                    chat_id INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()

    def _get_connection(self):
        return sqlite3.connect('messages.db', check_same_thread=False)

    def add_message(self, message_id, chat_id):
        with self._get_connection() as conn:
            conn.execute(
                'INSERT OR IGNORE INTO sent_messages VALUES (?, ?, CURRENT_TIMESTAMP)',
                (message_id, chat_id)
            )
            conn.commit()

    def message_exists(self, message_id):
        with self._get_connection() as conn:
            cursor = conn.execute(
                'SELECT 1 FROM sent_messages WHERE message_id = ?',
                (message_id,)
            )
            return bool(cursor.fetchone())

# تحكم الفيض (Flood Control) كما هو
class FloodControl:
    def __init__(self, max_messages=5, period=10):
        self.max_messages = max_messages
        self.period = period
        self.history = deque(maxlen=max_messages)
        self.lock = threading.Lock()

    def check_flood(self):
        with self.lock:
            now = time()
            self.history.append(now)
            if len(self.history) < self.max_messages:
                return False
            return (now - self.history[0]) < self.period

# +++ فئة EnhancedTelegramClient مع محاولات إعادة الاتصال +++
class EnhancedTelegramClient:
    def __init__(self, config=None):
        self.config = config
        self.client = None
        self.max_retries = 3
        self.retry_delay = 5

    async def connect(self):
        api_id_str = self.config.get("API_ID", "").strip()
        if not api_id_str:
            raise ValueError("API_ID is missing")
        api_id = int(api_id_str)
        api_hash = self.config.get("API_HASH", "").strip()
        for attempt in range(self.max_retries):
            try:
                self.client = TelegramClient(
                    'telegram_monitor',
                    api_id,
                    api_hash
                )
                await self.client.connect()
                return True
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise e
                await asyncio.sleep(self.retry_delay)
        return False

# التطبيق الرئيسي مع الواجهة
class TelegramMonitorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Telegram Monitor")
        self.geometry("1100x700")
        base_path = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(base_path, "the_icon_app.ico")  
        self.iconbitmap(icon_path)
        self.message_queue = queue.Queue()
        self.running = False
        self.db = SentMessageDB()
        self.flood_control = FloodControl()
        self.login_condition = threading.Condition()
        self.phone_number = None
        self.code = None
        self.password = None
        self.masked_entries = {}

        # إنشاء الواجهات
        self.create_widgets()

        # تهيئة مدير التكوين المشفر قبل استخدامه
        self.config_manager = SecureConfigManager()
        self.connection_status = tk.StringVar(value="Disconnected")
        self.setup_connection_status_indicator()

        # تحميل الإعدادات: الحقول API_ID وAPI_HASH وuser_id تُملأ إذا كانت موجودة
        self.load_initial_config()
        
        self.after(100, self.process_messages)

    def create_widgets(self):
        # الجزء العلوي من النافذة
        top_frame = tk.Frame(self, height=233)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)

        # حقول الإدخال للـ API_ID, API_HASH, وUser ID
        entries = [
            ("API ID", "api_id_entry", True),
            ("API Hash", "api_hash_entry", True),
            ("User ID", "user_id_entry", False)
        ]
        for i, (label_text, var_name, needs_mask) in enumerate(entries):
            tk.Label(top_frame, text=label_text).grid(row=i, column=0, sticky=tk.W, pady=2)
            entry = tk.Entry(top_frame, width=40)
            entry.grid(row=i, column=1, padx=5, pady=2)
            setattr(self, var_name, entry)
            if needs_mask:
                mask_btn = tk.Button(top_frame, text="OK", width=4,
                                     command=lambda e=entry: self.mask_entry(e))
                mask_btn.grid(row=i, column=2, padx=5)
                self.masked_entries[entry] = False

        # زر بدء المراقبة
        self.start_btn = tk.Button(top_frame, text="Start Monitoring", 
                                   command=self.toggle_monitoring)
        self.start_btn.grid(row=3, column=0, columnspan=2, pady=10)

        # زر "My GitHub" كبير في نفس الجزء العلوي
        github_btn = tk.Button(top_frame, text="My GitHub", font=("Arial", 14, "bold"),
                               command=self.open_github, bg="#4CAF50", fg="white")
        github_btn.grid(row=0, column=3, rowspan=2, padx=20, pady=5, sticky="nsew")

        # زر "# HOW IT WORK Button" كبير في نفس الجزء العلوي
        how_it_work_btn = tk.Button(top_frame, text="HOW IT WORK", font=("Arial", 14, "bold"),
                                    command=self.open_how_it_work, bg="#0088cc", fg="white")
        how_it_work_btn.grid(row=2, column=3, rowspan=2, padx=20, pady=5, sticky="nsew")



        # أزرار إعدادات الكلمات المفتاحية والملصقات
        config_frame = tk.Frame(self)
        config_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)
        self.keyword_btn = tk.Button(config_frame, text="Configure Keywords", 
                                     command=lambda: self._create_editable_dialog("Configure Keywords", "keywords"))
        self.keyword_btn.pack(side=tk.LEFT, padx=5)
        self.sticker_btn = tk.Button(config_frame, text="Configure Stickers", 
                                     command=lambda: self._create_editable_dialog("Configure Stickers", "stickers"))
        self.sticker_btn.pack(side=tk.LEFT, padx=5)

        # منطقة السجل (Log)
        log_frame = tk.Frame(self)
        log_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.log_area = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=15)
        self.log_area.pack(fill=tk.BOTH, expand=True)
        self.log_area.configure(state='disabled')

        # شريط الحالة في الأسفل
        self.status_frame = tk.Frame(self, height=20)
        self.status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_label = tk.Label(self.status_frame, text="Status: Ready", anchor=tk.W)
        self.status_label.pack(side=tk.LEFT, padx=10)
        # إضافة نص "Created by : Abdelrahman"
        self.creator_label = tk.Label(self.status_frame, text="Created by : Abdelrahman", anchor=tk.E)
        self.creator_label.pack(side=tk.RIGHT, padx=10)

    def mask_entry(self, entry):
        if self.masked_entries.get(entry, False):
            entry.config(show='')
            self.masked_entries[entry] = False
        else:
            entry.config(show='*')
            self.masked_entries[entry] = True

    # دالة فتح رابط GitHub
    def open_github(self):
        webbrowser.open("https://github.com/abdoayman45")

    def open_how_it_work(self):
        webbrowser.open("https://t.me/tele_monitor_app")


    # تحميل الإعدادات من الملف المشفر
    def load_initial_config(self):
        config = self.config_manager.load_config()
        self.api_id_entry.insert(0, config.get("API_ID", ""))
        self.api_hash_entry.insert(0, config.get("API_HASH", ""))
        self.user_id_entry.insert(0, config.get("user_id", ""))

    # إعداد مؤشر حالة الاتصال مع تغيير اللون بناءً على الحالة
    def setup_connection_status_indicator(self):
        status_frame = ttk.Frame(self.status_frame)
        status_frame.pack(side=tk.RIGHT, padx=10)
        ttk.Label(status_frame, text="Connection:").pack(side=tk.LEFT)
        self.connection_label = ttk.Label(status_frame, textvariable=self.connection_status, foreground="red")
        self.connection_label.pack(side=tk.LEFT)
        self.connection_status.trace_add("write", self.update_status_color)

    def update_status_color(self, *args):
        status = self.connection_status.get()
        if status == "Connected":
            self.connection_label.config(foreground="green")
        else:
            self.connection_label.config(foreground="red")

    # تبديل بدء/إيقاف المراقبة
    def toggle_monitoring(self):
        if self.running:
            self.running = False
            self.start_btn.config(text="Start Monitoring")
            self.status_label.config(text="Status: Monitoring Stopped")
            self.log("Monitoring stopped by user")
        else:
            self.start_monitoring()

    # نافذة تحرير الإعدادات (الكلمات المفتاحية أو الملصقات)
    def _create_editable_dialog(self, title, config_key):
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.geometry("500x400")
        dialog.transient(self)
        dialog.grab_set()

        main_frame = tk.Frame(dialog)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # إذا كان تعديل الكلمات المفتاحية، نضيف ملاحظة توضيحية
        if config_key == "keywords":
            note_label = tk.Label(main_frame, text="Note: For each keyword, add it three times as follows:\nabdo\nAbdo\nABDO", justify="left", fg="blue")
            note_label.pack(fill=tk.X, pady=(0,5))

        if config_key != "keywords":
            note_label = tk.Label(main_frame, text="Note: For each Sticker, add it Like this :\n5997064617816231180", justify="left", fg="blue")
            note_label.pack(fill=tk.X, pady=(0,5))


        # قائمة مع شريط تمرير
        list_frame = tk.Frame(main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, selectmode=tk.SINGLE)
        self.listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.listbox.yview)

        # حقل الإدخال والأزرار
        entry_frame = tk.Frame(main_frame)
        entry_frame.pack(fill=tk.X, pady=5)
        self.entry = tk.Entry(entry_frame)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        btn_frame = tk.Frame(entry_frame)
        btn_frame.pack(side=tk.LEFT)
        tk.Button(btn_frame, text="Add", command=lambda: self._add_item(config_key)).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="Delete", command=lambda: self._delete_item(config_key)).pack(side=tk.LEFT, padx=2)

        # تحميل العناصر المحفوظة
        config = self.config_manager.load_config()
        for item in config.get(config_key, []):
            self.listbox.insert(tk.END, item)

        # أزرار الحفظ والإلغاء
        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=5)
        tk.Button(btn_frame, text="Save", command=lambda: self._save_config(config_key, dialog), width=10).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel", command=dialog.destroy, width=10).pack(side=tk.LEFT, padx=5)

    def _add_item(self, config_key):
        new_item = self.entry.get().strip()
        if new_item:
            self.listbox.insert(tk.END, new_item)
            self.entry.delete(0, tk.END)
        else:
            messagebox.showwarning("Empty Entry", "Please enter a value before adding")

    def _delete_item(self, config_key):
        try:
            selected_index = self.listbox.curselection()[0]
            self.listbox.delete(selected_index)
        except IndexError:
            messagebox.showwarning("No Selection", "Please select an item to delete")

    def _save_config(self, config_key, dialog):
        items = [self.listbox.get(i) for i in range(self.listbox.size())]
        config = self.config_manager.load_config()
        config[config_key] = items
        self.save_config(config)
        dialog.destroy()
        self.log(f"{config_key.capitalize()} configuration updated")

    def configure_keywords(self):
        self._create_editable_dialog("Configure Keywords", "keywords")

    def configure_stickers(self):
        self._create_editable_dialog("Configure Stickers", "stickers")

    # تحديث إعدادات الاتصال
    def start_monitoring(self):
        if not self.validate_credentials():
            return
        
        # تحديث إعدادات العميل مع الاحتفاظ ببيانات BOT_TOKEN الحالية من الملف المشفر
        current_config = self.config_manager.load_config()
        config = {
            "API_ID": self.api_id_entry.get().strip(),
            "API_HASH": self.api_hash_entry.get().strip(),
            "user_id": self.user_id_entry.get().strip(),
            "keywords": current_config.get('keywords', []),
            "stickers": current_config.get('stickers', []),
            "BOT_TOKEN": current_config.get("BOT_TOKEN", DEFAULT_CONFIG["BOT_TOKEN"])
        }
        self.save_config(config)
        
        session_file = 'telegram_monitor.session'
        if os.path.exists(session_file):
            choice = messagebox.askyesno(
                "Session Found",
                "An existing session was found.\n\nYes: Delete and create new session\nNo: Continue with existing session"
            )
            if choice:
                try:
                    os.remove(session_file)
                    self.log("Session deleted. New login required.")
                except Exception as e:
                    self.log(f"Error deleting session: {str(e)}")
                    self.running = False
                    self.start_btn.config(text="Start Monitoring")
                    return

        self.running = True
        self.start_btn.config(text="Stop Monitoring")
        self.status_label.config(text="Status: Monitoring Active")
        self.log("Initializing monitoring...")
        
        monitor_thread = threading.Thread(target=self.run_telethon_client, daemon=True)
        monitor_thread.start()

    # التحقق من صحة بيانات العميل
    def validate_credentials(self):
        try:
            if not self.api_id_entry.get().strip():
                raise ValueError("API_ID is required")
            int(self.api_id_entry.get().strip())
            if not self.api_hash_entry.get().strip() or len(self.api_hash_entry.get().strip()) != 32:
                raise ValueError("Invalid API_HASH")
            if not self.user_id_entry.get().strip():
                raise ValueError("User ID is required")
            return True
        except Exception as e:
            self.log(f"Configuration Error: {str(e)}")
            messagebox.showerror("Invalid Credentials", 
                "Please check:\n1. API_ID must be a valid integer\n2. API_HASH must be 32 characters\n3. User ID is required")
            return False

    # حفظ التكوين في الملف المشفر
    def save_config(self, config):
        merged_config = {**DEFAULT_CONFIG, **config}
        self.config_manager.save_config(merged_config)

    def log(self, message):
        self.log_area.configure(state='normal')
        self.log_area.insert(tk.END, f"[{get_timestamp()}] {message}\n")
        self.log_area.configure(state='disabled')
        self.log_area.see(tk.END)

    def process_messages(self):
        while not self.message_queue.empty():
            message = self.message_queue.get_nowait()
            if isinstance(message, tuple):
                if message[0] == "login_required":
                    self.ask_phone_number()
                elif message[0] == "code_required":
                    self.ask_code()
                elif message[0] == "password_required":
                    self.ask_password()
            else:
                self.log(message)
        self.after(100, self.process_messages)

    def ask_phone_number(self):
        dialog = tk.Toplevel(self)
        dialog.title("Phone Number Required")
        dialog.transient(self)
        dialog.grab_set()

        # تحديد حجم النافذة الفرعية
        width = 300
        height = 150

        # تحديث بيانات النافذة الرئيسية للتأكد من دقة الأبعاد والموقع
        self.update_idletasks()
        
        # الحصول على موقع وحجم النافذة الرئيسية
        parent_x = self.winfo_rootx()
        parent_y = self.winfo_rooty()
        parent_width = self.winfo_width()
        parent_height = self.winfo_height()
        
        # حساب مركز النافذة الرئيسية وتحديد موقع النافذة الفرعية بحيث تظهر في وسطها
        x = parent_x + (parent_width // 2) - (width // 2)
        y = parent_y + (parent_height // 2) - (height // 2)
        
        dialog.geometry(f"{width}x{height}+{x}+{y}")

        tk.Label(dialog, text="Enter phone number (international format):").pack(padx=20, pady=5)
        phone_entry = tk.Entry(dialog)
        phone_entry.pack(padx=20, pady=5)

        def submit():
            self.phone_number = phone_entry.get().strip()
            dialog.destroy()
            with self.login_condition:
                self.login_condition.notify()

        tk.Button(dialog, text="Submit", command=submit).pack(pady=10)
        self.wait_window(dialog)


    def ask_code(self):
        dialog = tk.Toplevel(self)
        dialog.title("Verification Code Required")
        dialog.transient(self)
        dialog.grab_set()


        # تحديد حجم النافذة الفرعية
        width = 300
        height = 150

        # تحديث بيانات النافذة الرئيسية للتأكد من دقة الأبعاد والموقع
        self.update_idletasks()
        
        # الحصول على موقع وحجم النافذة الرئيسية
        parent_x = self.winfo_rootx()
        parent_y = self.winfo_rooty()
        parent_width = self.winfo_width()
        parent_height = self.winfo_height()
        
        # حساب مركز النافذة الرئيسية وتحديد موقع النافذة الفرعية بحيث تظهر في وسطها
        x = parent_x + (parent_width // 2) - (width // 2)
        y = parent_y + (parent_height // 2) - (height // 2)
        
        dialog.geometry(f"{width}x{height}+{x}+{y}")


        tk.Label(dialog, text="Enter verification code:").pack(padx=20, pady=5)
        code_entry = tk.Entry(dialog)
        code_entry.pack(padx=20, pady=5)

        def submit():
            self.code = code_entry.get().strip()
            dialog.destroy()
            with self.login_condition:
                self.login_condition.notify()

        tk.Button(dialog, text="Submit", command=submit).pack(pady=10)
        self.wait_window(dialog)

    def ask_password(self):
        dialog = tk.Toplevel(self)
        dialog.title("2FA Password Required")
        dialog.transient(self)
        dialog.grab_set()

        # تحديد حجم النافذة الفرعية
        width = 300
        height = 150

        # تحديث بيانات النافذة الرئيسية للتأكد من دقة الأبعاد والموقع
        self.update_idletasks()
        
        # الحصول على موقع وحجم النافذة الرئيسية
        parent_x = self.winfo_rootx()
        parent_y = self.winfo_rooty()
        parent_width = self.winfo_width()
        parent_height = self.winfo_height()
        
        # حساب مركز النافذة الرئيسية وتحديد موقع النافذة الفرعية بحيث تظهر في وسطها
        x = parent_x + (parent_width // 2) - (width // 2)
        y = parent_y + (parent_height // 2) - (height // 2)
        
        dialog.geometry(f"{width}x{height}+{x}+{y}")


        tk.Label(dialog, text="Enter your 2FA password:").pack(padx=20, pady=5)
        pwd_entry = tk.Entry(dialog, show='*')
        pwd_entry.pack(padx=20, pady=5)

        def submit():
            self.password = pwd_entry.get().strip()
            dialog.destroy()
            with self.login_condition:
                self.login_condition.notify()

        tk.Button(dialog, text="Submit", command=submit).pack(pady=10)
        self.wait_window(dialog)

    # دالة run_telethon_client التي تدير الاتصال والتعامل مع الرسائل
    def run_telethon_client(self):
        async def async_main():
            try:
                config = {
                    "API_ID": self.api_id_entry.get().strip(),
                    "API_HASH": self.api_hash_entry.get().strip(),
                    "user_id": self.user_id_entry.get().strip()
                }
                client_wrapper = EnhancedTelegramClient(config)
                if not await client_wrapper.connect():
                    raise ConnectionError("Connection failed after retries")
                self.connection_status.set("Connected")
                client = client_wrapper.client
                if not await client.is_user_authorized():
                    self.message_queue.put(("login_required", None))
                    with self.login_condition:
                        self.login_condition.wait()
                    await client.send_code_request(self.phone_number)
                    self.message_queue.put(("code_required", None))
                    with self.login_condition:
                        self.login_condition.wait()
                    try:
                        await client.sign_in(self.phone_number, self.code)
                    except SessionPasswordNeededError:
                        self.message_queue.put(("password_required", None))
                        with self.login_condition:
                            self.login_condition.wait()
                        await client.sign_in(password=self.password)
                self.message_queue.put("Connected successfully")

                # تحميل BOT_TOKEN من التكوين المشفر وتفكيكه باستخدام BOT_ENCRYPTION_KEY
                full_config = self.config_manager.load_config()
                encrypted_bot_token = full_config.get("BOT_TOKEN", DEFAULT_CONFIG["BOT_TOKEN"])
                bot_token = fernet.decrypt(encrypted_bot_token.encode()).decode()

                @client.on(events.NewMessage(incoming=True))
                async def message_handler(event):
                    if self.flood_control.check_flood():
                        self.message_queue.put("Flood control active - skipping messages")
                        return
                    try:
                        msg = event.message
                        if self.db.message_exists(msg.id):
                            return
                        sender = await event.get_sender()
                        # استثناء الرسائل المرسلة من البوت نفسه
                        if sender and getattr(sender, 'bot', False):
                            return
                        chat = await event.get_chat()
                        sender_name = await self.get_entity_name(sender)
                        self.message_queue.put(f"New message from {sender_name}")
                        message_text = msg.text or msg.raw_text
                        config = self.config_manager.load_config()
                        if message_text and config.get('keywords'):
                            for keyword in config['keywords']:
                                if re.search(rf'\b{re.escape(keyword)}\b', message_text, re.I):
                                    await self.send_alert(
                                        msg, sender, chat,
                                        bot_token=bot_token,
                                        user_id=self.user_id_entry.get().strip(),
                                        keyword=keyword
                                    )
                                    self.db.add_message(msg.id, chat.id)
                                    break
                        if msg.sticker and config.get('stickers'):
                            sticker_id = str(msg.sticker.id)
                            if sticker_id in config['stickers']:
                                await self.send_alert(
                                    msg, sender, chat,
                                    bot_token=bot_token,
                                    user_id=self.user_id_entry.get().strip(),
                                    sticker={'name': 'Sticker'}
                                )
                                self.db.add_message(msg.id, chat.id)
                            else:
                                self.message_queue.put(f"New Sticker ID : {sticker_id}")
                        else:
                            sticker_id = str(msg.sticker.id)
                            self.message_queue.put(f"New Sticker ID : {sticker_id}")


                    except Exception as e:
                        self.message_queue.put(f"Error processing message: {str(e)}")

                await client.run_until_disconnected()

            except Exception as e:
                self.message_queue.put(f"Connection error: {str(e)}")
                self.running = False
                self.start_btn.config(text="Start Monitoring")
                self.status_label.config(text="Status: Connection Error")

            finally:
                self.connection_status.set("Disconnected")
                if client and client.is_connected():
                    await client.disconnect()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(async_main())
        except Exception as e:
            self.message_queue.put(f"Unexpected error: {str(e)}")
        finally:
            loop.close()


    async def get_entity_name(self, entity):
        if isinstance(entity, User):
            return entity.first_name or entity.username or "Unknown User"
        if isinstance(entity, Channel):
            return entity.title
        return "Unknown"

    # تحسين دالة send_alert
    async def send_alert(self, msg, sender, chat, **kwargs):
        try:
            message_preview = self._generate_preview(msg)
            alert_text = f"🔔 **New Alert**\n\n{message_preview}\n\n"
            sender_name = await self.get_entity_name(sender)
            alert_text += f"**Sender:** {sender_name}\n"
            chat_name = await self.get_entity_name(chat)
            alert_text += f"**Chat:** {chat_name}\n"
            message_link = await self.format_message_link(chat.id, msg.id)
            alert_text += f"**Message Link:** [View Message]({message_link})\n\n"
            if 'keyword' in kwargs:
                alert_text += f"**Detected Keyword:** `{kwargs['keyword']}`\n"
            elif 'sticker' in kwargs:
                alert_text += f"**Detected Sticker:** {kwargs['sticker']['name']}\n"
            from aiogram import Bot
            bot = Bot(token=kwargs.get("bot_token"))
            await bot.send_message(
                chat_id=kwargs.get("user_id"),
                text=alert_text,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
        except Exception as e:
            self.log(f"Alert Failed: {str(e)}")
            await self.handle_alert_retry(msg)

    def _generate_preview(self, msg):
        if msg.text:
            return f"Message preview: {msg.text[:100]}..." if len(msg.text) > 100 else msg.text
        elif msg.sticker:
            return f"Sticker detected: {getattr(msg.sticker, 'alt', 'No alt text')}"
        return "Media content detected"

    async def handle_alert_retry(self, msg):
        for attempt in range(3):
            try:
                await asyncio.sleep(2 ** attempt)
                break
            except Exception as e:
                if attempt == 2:
                    self.log(f"Permanent alert failure: {str(e)}")

    async def format_message_link(self, chat_id, message_id):
        if isinstance(chat_id, int):
            if str(chat_id).startswith('-100'):
                channel_id = str(chat_id).replace('-100', '')
                return f'https://t.me/c/{channel_id}/{message_id}'
            return f'https://t.me/c/{chat_id}/{message_id}'
        return ""

def get_timestamp():
    return strftime("%Y-%m-%d %H:%M:%S", localtime())

if __name__ == "__main__":
    app = TelegramMonitorApp()
    app.mainloop()
