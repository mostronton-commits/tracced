"""Акаунт = гаманець Solana. Вхід — підпис короткого тексту (Sign in with Solana), без транзакції.

Сервер видає одноразовий код (nonce), гаманець підписує текст із доменом, кодом і часом, сервер
перевіряє підпис відкритим ключем (він же адреса) і ставить свою куку. Окремої реєстрації немає:
перший вхід створює файл output/early/accounts/<pubkey>.json зі збереженими гаманцями й аналізами.

Тут лише чиста логіка без aiohttp: її можна тестувати без сервера.
"""
import base64
import datetime
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time

try:
    from nacl.exceptions import BadSignatureError
    from nacl.signing import VerifyKey
except ImportError:                      # хост без PyNaCl: підпис перевірити не вийде, решта працює
    VerifyKey = BadSignatureError = None

log = logging.getLogger("early.accounts")

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(B58)}
PUBKEY_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

STATEMENT = "Sign in to save wallets and analyses. No transaction, no fees."
_HEAD = " wants you to sign in with your Solana account:"
MAX_MESSAGE = 2048

MAX_WALLETS, MAX_ANALYSES, MAX_NOTE = 500, 200, 200
WALLET_FIELDS = ("from_job", "mint", "symbol", "entry_mcap", "invested_usd", "multiple", "tags")
ANALYSIS_FIELDS = ("mint", "symbol", "t_from", "t_to", "n", "best")


# ───────────────────────── base58 ─────────────────────────

def b58decode(s):
    """Base58 (алфавіт Bitcoin/Solana) → байти. ValueError на чужий символ."""
    if not isinstance(s, str) or not s:
        raise ValueError("empty")
    n = 0
    for c in s:
        try:
            n = n * 58 + _B58_INDEX[c]
        except KeyError:
            raise ValueError("not base58") from None
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + raw


def b58encode(b):
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    pad = len(b) - len(b.lstrip(b"\x00"))
    return "1" * pad + out


def valid_pubkey(s):
    """Адреса Solana: base58 і рівно 32 байти. Єдина перевірка перед тим, як ключ стане ім'ям файлу."""
    if not isinstance(s, str) or not PUBKEY_RE.match(s):
        return False
    try:
        return len(b58decode(s)) == 32
    except ValueError:
        return False


# ───────────────────────── message ─────────────────────────

def build_message(domain, pubkey, nonce, issued_at):
    """Текст, який підписує гаманець. Той самий формат збирає браузер із полів відповіді /auth/nonce."""
    return f"{domain}{_HEAD}\n{pubkey}\n\n{STATEMENT}\n\nNonce: {nonce}\nIssued At: {issued_at}"


def parse_message(text):
    """Поля з тексту. Будь-яке відхилення від build_message — ValueError."""
    if not isinstance(text, str) or not text or len(text) > MAX_MESSAGE:
        raise ValueError("bad message")
    lines = text.split("\n")
    if len(lines) != 7 or not lines[0].endswith(_HEAD) or lines[2] or lines[4] or lines[3] != STATEMENT:
        raise ValueError("bad message")
    if not lines[5].startswith("Nonce: ") or not lines[6].startswith("Issued At: "):
        raise ValueError("bad message")
    m = {"domain": lines[0][: -len(_HEAD)], "pubkey": lines[1],
         "nonce": lines[5][len("Nonce: "):], "issued_at": lines[6][len("Issued At: "):]}
    if not m["domain"] or not NONCE_RE.match(m["nonce"]) or parse_issued_at(m["issued_at"]) is None \
            or build_message(**m) != text:
        raise ValueError("bad message")
    return m


def issued_at(now=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now if now is not None else time.time()))


def parse_issued_at(s):
    """ISO-час з /auth/nonce → секунди, або None."""
    try:
        d = datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None
    return d.timestamp()


# ───────────────────────── signature ─────────────────────────

def decode_signature(sig):
    """Підпис ed25519 як base58 або base64 → 64 байти, або None."""
    if not isinstance(sig, str) or not (40 <= len(sig) <= 128):
        return None
    for dec in (b58decode, lambda s: base64.b64decode(s, validate=True)):
        try:
            raw = dec(sig)
        except Exception:  # noqa: BLE001 — не той алфавіт, пробуємо інший
            continue
        if len(raw) == 64:
            return raw
    return None


def verify_signature(pubkey, message, signature):
    """Чи підписав власник pubkey саме цей текст. Підпис у логи не потрапляє."""
    if VerifyKey is None:
        raise RuntimeError("PyNaCl is not installed")
    raw = decode_signature(signature)
    if raw is None or not valid_pubkey(pubkey) or not isinstance(message, str):
        return False
    try:
        VerifyKey(b58decode(pubkey)).verify(message.encode("utf-8"), raw)
        return True
    except BadSignatureError:
        return False
    except Exception:  # noqa: BLE001 — зіпсований ключ тощо: це не наш збій, а невдалий вхід
        return False


# ───────────────────────── nonce ─────────────────────────

class NonceStore:
    """Одноразові коди для входу: живуть ttl_s, спалюються при першому використанні."""

    def __init__(self, ttl_s=300, cap=5000):
        self.ttl_s, self.cap = ttl_s, cap
        self.live = {}                    # nonce -> expires at (s)
        self.lock = threading.Lock()

    def _prune(self, now):
        dead = [n for n, exp in self.live.items() if exp <= now]
        for n in dead:
            del self.live[n]
        if len(self.live) >= self.cap:    # хтось набирає коди без входу: найстарші йдуть геть
            for n in sorted(self.live, key=self.live.get)[: len(self.live) - self.cap + 1]:
                del self.live[n]

    def issue(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            self._prune(now)
            n = secrets.token_urlsafe(24)
            self.live[n] = now + self.ttl_s
        return n

    def consume(self, nonce, now=None):
        now = time.time() if now is None else now
        with self.lock:
            exp = self.live.pop(nonce, None)
        return exp is not None and exp > now


# ───────────────────────── cookie ─────────────────────────

def _acct_key(secret):
    """Ключ підпису куки акаунта. Від пароля бети не залежить: це різні входи."""
    return hashlib.sha256(b"early-acct:" + secret.encode()).digest()


def sign_acct(secret, pubkey, exp):
    mac = hmac.new(_acct_key(secret), f"{pubkey}.{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{pubkey}.{exp}.{mac}"


def read_acct(secret, token, now=None):
    """Адреса з куки, або None, якщо кука чужа, зіпсована чи прострочена."""
    if not token or not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) != 3 or not valid_pubkey(parts[0]):
        return None
    try:
        exp = int(parts[1])
    except ValueError:
        return None
    if exp < (time.time() if now is None else now):
        return None
    return parts[0] if hmac.compare_digest(sign_acct(secret, parts[0], exp), token) else None


# ───────────────────────── store ─────────────────────────

class AccountError(Exception):
    """Текст для людини (400)."""


def _now_ms():
    return int(time.time() * 1000)


def _empty(pubkey):
    return {"pubkey": pubkey, "created_ms": _now_ms(), "last_seen_ms": _now_ms(), "wallets": {}, "analyses": {}}


class AccountStore:
    """Один JSON на акаунт, атомарний запис, один замок на читання-зміну-запис (один процес)."""

    def __init__(self, dir):
        self.dir = str(dir)
        os.makedirs(self.dir, exist_ok=True)
        self.lock = threading.Lock()

    def path(self, pubkey):
        if not valid_pubkey(pubkey):
            raise ValueError("bad pubkey")
        return os.path.join(self.dir, pubkey + ".json")

    def exists(self, pubkey):
        return os.path.exists(self.path(pubkey))

    def load(self, pubkey):
        path = self.path(pubkey)
        try:
            with open(path, encoding="utf-8") as f:
                a = json.load(f)
        except FileNotFoundError:
            return _empty(pubkey)
        except Exception as e:  # noqa: BLE001 — битий файл не валить сторінку
            log.warning("account file unreadable %s: %s", pubkey[:8], e)
            return _empty(pubkey)
        a["pubkey"] = pubkey
        a.setdefault("wallets", {})
        a.setdefault("analyses", {})
        return a

    def save(self, a):
        path = self.path(a["pubkey"])
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(a, f, ensure_ascii=False)
        os.replace(tmp, path)

    def _update(self, pubkey, fn):
        with self.lock:
            a = self.load(pubkey)
            out = fn(a)
            a["last_seen_ms"] = _now_ms()
            self.save(a)
        return out

    def touch(self, pubkey, wallet_app=None):
        """Перший вхід створює акаунт; кожен вхід рахується і запам'ятовує, яким гаманцем зайшли."""
        def fn(a):
            a["signins"] = int(a.get("signins") or 0) + 1
            if wallet_app:
                a["wallet_app"] = str(wallet_app)[:40]
            return a
        return self._update(pubkey, fn)

    def all(self):
        """Усі акаунти, найактивніші першими — для сторінки власника."""
        out = []
        for name in os.listdir(self.dir):
            if name.endswith(".json") and valid_pubkey(name[:-5]):
                out.append(self.load(name[:-5]))
        return sorted(out, key=lambda a: a.get("last_seen_ms") or 0, reverse=True)

    def add_wallets(self, pubkey, items):
        """items: словники з ключем wallet і полями WALLET_FIELDS → (додано, разом)."""
        def fn(a):
            added = 0
            for it in items:
                w = it.get("wallet")
                if not valid_pubkey(w) or w in a["wallets"]:
                    continue
                if len(a["wallets"]) >= MAX_WALLETS:
                    raise AccountError(f"Your watchlist is full ({MAX_WALLETS} wallets). Remove some first.")
                a["wallets"][w] = {"added_ms": _now_ms(), "note": "", **{k: it.get(k) for k in WALLET_FIELDS}}
                added += 1
            return added, len(a["wallets"])
        return self._update(pubkey, fn)

    def remove_wallet(self, pubkey, wallet):
        return self._update(pubkey, lambda a: a["wallets"].pop(wallet, None) is not None)

    def set_note(self, pubkey, wallet, note):
        note = " ".join(str(note or "").split())[:MAX_NOTE]

        def fn(a):
            w = a["wallets"].get(wallet)
            if w is None:
                return False
            w["note"] = note
            return True
        return self._update(pubkey, fn)

    def add_analysis(self, pubkey, job_id, summary):
        if not JOB_ID_RE.match(str(job_id or "")):
            raise AccountError("Bad analysis id.")

        def fn(a):
            if job_id in a["analyses"]:
                return False, len(a["analyses"])
            if len(a["analyses"]) >= MAX_ANALYSES:
                raise AccountError(f"My analyses is full ({MAX_ANALYSES}). Remove some first.")
            a["analyses"][job_id] = {"added_ms": _now_ms(), **{k: summary.get(k) for k in ANALYSIS_FIELDS}}
            return True, len(a["analyses"])
        return self._update(pubkey, fn)

    def remove_analysis(self, pubkey, job_id):
        return self._update(pubkey, lambda a: a["analyses"].pop(str(job_id), None) is not None)


class EventLog:
    """Що роблять акаунти на сайті: один JSONL-файл, читає лише власник на /admin."""

    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.Lock()

    def add(self, pubkey, event, **extra):
        rec = {"ts_ms": _now_ms(), "pubkey": pubkey, "event": event, **extra}
        try:
            with self.lock, open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError as e:                          # журнал не має валити дію користувача
            log.warning("event log: %s", e)

    def tail(self, n=100):
        try:
            with open(self.path, encoding="utf-8") as f:
                lines = f.readlines()[-n:]
        except FileNotFoundError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out[::-1]
