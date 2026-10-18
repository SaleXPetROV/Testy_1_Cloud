"""
Email Service for GRAM City Builder
Handles sending password reset codes via SMTP or Resend API
"""
import os
import smtplib
import asyncio
import secrets  # F6: cryptographically secure RNG for verification codes
import string
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
import logging

logger = logging.getLogger(__name__)

# Try to import resend
try:
    import resend
    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False
    logger.warning("Resend library not installed - using SMTP only")

# In-memory storage for reset codes (in production, use Redis or DB)
reset_codes = {}

# In-memory storage for email verification codes
email_verification_codes = {}

# In-memory storage for login email-2FA codes (separate from registration codes)
login_codes = {}

# Configure Resend if API key available. Strip whitespace + accidental quotes
# so a stray char in the .env doesn't turn into "API key is invalid".
def _clean(v: str) -> str:
    v = (v or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1].strip()
    return v


def _mask_email(v: str) -> str:
    """Mask an email for safe logging: keep first char + domain."""
    try:
        name, _, dom = (v or "").partition("@")
        if not dom:
            return "<no-email>"
        return f"{(name[:1] if name else '?')}***@{dom}"
    except Exception:
        return "<email>"

RESEND_API_KEY = _clean(os.environ.get('RESEND_API_KEY', ''))
_SENDER_FALLBACK = 'Support GRAM CITY <support@gramcity.games>'
SENDER_EMAIL = _clean(os.environ.get('SENDER_EMAIL', '')) or _SENDER_FALLBACK
# Email владельца Resend аккаунта оставлен как опциональный fallback для теста.
# В проде письма уходят реальному получателю (нужен верифицированный домен + SENDER_EMAIL на нём).
RESEND_OWNER_EMAIL = os.environ.get('RESEND_OWNER_EMAIL', 'sanyanazarov212@gmail.com')


def _sender_domain(sender: str) -> str:
    """Extract the domain from a `Name <addr@domain>` or bare `addr@domain`."""
    s = (sender or "").strip()
    if "<" in s and ">" in s:
        s = s[s.find("<") + 1:s.find(">")]
    return s.rsplit("@", 1)[-1].strip().lower() if "@" in s else ""


def email_startup_diagnostics() -> None:
    """One-shot, secret-free startup log so prod email misconfig is obvious in
    the logs WITHOUT triggering a real reset. Diagnoses the #1 prod failure:
    a SENDER_EMAIL whose domain is not verified in Resend."""
    dom = _sender_domain(SENDER_EMAIL)
    logger.info(
        "[email] startup: resend_installed=%s resend_key_set=%s sender=%r sender_domain=%s smtp_user_set=%s",
        RESEND_AVAILABLE, bool(RESEND_API_KEY), SENDER_EMAIL, dom or "<none>",
        bool(os.environ.get("SMTP_USER")),
    )
    if not RESEND_API_KEY:
        logger.warning("[email] startup: RESEND_API_KEY is EMPTY — Resend delivery disabled.")
    if SENDER_EMAIL == _SENDER_FALLBACK or dom == "gramcity.games":
        logger.warning(
            "[email] startup: SENDER_EMAIL is using the UNVERIFIED fallback domain %r. "
            "Set SENDER_EMAIL to an address on your VERIFIED Resend domain "
            "(e.g. 'Support GRAM CITY <support@gramcity.app>'), otherwise Resend will "
            "reject all outbound mail and password-reset codes will silently NOT arrive.",
            dom or "gramcity.games",
        )


if RESEND_AVAILABLE and RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY
    logger.info("Resend API configured for email delivery")



async def send_email_via_resend(to_email: str, subject: str, html_content: str, send_to_admin: bool = False) -> bool:
    """
    Send email to the REAL recipient using Resend API (async).
    Требования для доставки внешним адресам: верифицированный домен в Resend
    и SENDER_EMAIL на этом домене. Без домена Resend отдаёт только на адрес владельца аккаунта.
    """
    if not RESEND_AVAILABLE or not RESEND_API_KEY:
        logger.error(
            "[email] Resend NOT available (installed=%s, api_key_set=%s) — cannot send to %s",
            RESEND_AVAILABLE, bool(RESEND_API_KEY), _mask_email(to_email),
        )
        return False
    logger.info("[email] Resend send START to=%s from=%r subject=%r",
                _mask_email(to_email), SENDER_EMAIL, subject)
    
    # Брендированная обёртка письма для пользователя
    admin_html = f"""
<html>
<body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #0a0a0f; color: #ffffff; padding: 16px 10px; margin: 0;">
    <div style="max-width: 600px; margin: 0 auto;">
        <!-- Основное содержимое -->
        <div style="background: linear-gradient(135deg, #1a1a2e 0%, #0f0f1a 100%); border-radius: 12px; border: 1px solid rgba(0,255,255,0.2);">
            {html_content}
        </div>
        
        <!-- Footer -->
        <div style="text-align: center; padding: 20px; color: #666; font-size: 12px;">
            <p>GRAM City Builder</p>
        </div>
    </div>
</body>
</html>
"""
    
    params = {
        "from": SENDER_EMAIL,
        "to": [to_email],
        "subject": subject,
        "html": admin_html
    }
    
    try:
        email_result = await asyncio.to_thread(resend.Emails.send, params)
        logger.info("[email] Resend SENT to=%s id=%s", _mask_email(to_email), email_result.get('id'))
        return True
    except Exception as e:
        logger.error("[email] Resend FAILED to=%s: %s", _mask_email(to_email), str(e))
        return False

def generate_reset_code() -> str:
    """Generate 8-character code with uppercase, lowercase letters and digits (mixed case for readability).

    F6: uses `secrets.choice` (CSPRNG) instead of `random.choice` (Mersenne
    Twister — predictable if internal state ever leaks).
    """
    characters = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(characters) for _ in range(8))

def generate_verification_code() -> str:
    """Generate 6-digit verification code. F6: CSPRNG."""
    return ''.join(secrets.choice(string.digits) for _ in range(6))

def store_verification_code(email: str, code: str, username: str, password_hash: str):
    """Store email verification code with user data"""
    email_verification_codes[email.lower()] = {
        "code": code,
        "username": username,
        "password_hash": password_hash,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
        "attempts": 0
    }

def verify_email_code(email: str, code: str) -> tuple[bool, str, dict]:
    """
    Verify email verification code
    Returns (success, message, user_data)
    """
    email_lower = email.lower()
    
    if email_lower not in email_verification_codes:
        return False, "no_code_requested", {}
    
    stored = email_verification_codes[email_lower]
    
    # Check expiration
    if datetime.now(timezone.utc) > stored["expires_at"]:
        del email_verification_codes[email_lower]
        return False, "code_expired", {}
    
    # Check attempts (max 5)
    if stored["attempts"] >= 5:
        del email_verification_codes[email_lower]
        return False, "too_many_attempts", {}
    
    # Verify code
    if stored["code"] != code:
        stored["attempts"] += 1
        return False, "invalid_code", {}
    
    # Success - get user data and remove code
    user_data = {
        "username": stored["username"],
        "password_hash": stored["password_hash"]
    }
    del email_verification_codes[email_lower]
    return True, "success", user_data

def store_reset_code(email: str, code: str):
    """Store reset code with 15 minute expiration"""
    logger.info(f"Storing reset code for {email.lower()}: '{code}'")
    reset_codes[email.lower()] = {
        "code": code,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
        "attempts": 0
    }

def verify_reset_code(email: str, code: str) -> tuple[bool, str]:
    """
    Verify reset code for email
    Returns (success, message)
    """
    email_lower = email.lower()
    
    if email_lower not in reset_codes:
        return False, "no_code_requested"
    
    stored = reset_codes[email_lower]
    
    # Check expiration
    if datetime.now(timezone.utc) > stored["expires_at"]:
        del reset_codes[email_lower]
        return False, "code_expired"
    
    # Check attempts (max 5)
    if stored["attempts"] >= 5:
        del reset_codes[email_lower]
        return False, "too_many_attempts"
    
    # Verify code (case-sensitive, strip whitespace only)
    if stored["code"] != code.strip():
        stored["attempts"] += 1
        return False, "invalid_code"
    
    # Success - remove code
    del reset_codes[email_lower]
    return True, "success"

def send_reset_email(to_email: str, code: str, language: str = "en") -> bool:
    """Send password reset email with code"""
    return send_email_with_code(to_email, code, language, "reset")

def send_verification_email(to_email: str, code: str, language: str = "en") -> bool:
    """Send email verification code"""
    return send_email_with_code(to_email, code, language, "verification")

# ─────────────────── Login email-2FA code ───────────────────
def store_login_code(email: str, code: str):
    """Store login verification code (5 attempts, 15 min expiry)."""
    login_codes[email.lower()] = {
        "code": code,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
        "attempts": 0,
    }

def verify_login_code(email: str, code: str) -> tuple[bool, str]:
    """Verify login email code. Returns (success, message).
    Possible messages: 'success', 'no_code_requested', 'code_expired',
    'too_many_attempts', 'invalid_code'.
    """
    email_lower = email.lower()
    if email_lower not in login_codes:
        return False, "no_code_requested"
    stored = login_codes[email_lower]
    if datetime.now(timezone.utc) > stored["expires_at"]:
        del login_codes[email_lower]
        return False, "code_expired"
    if stored["attempts"] >= 5:
        del login_codes[email_lower]
        return False, "too_many_attempts"
    if stored["code"] != (code or "").strip():
        stored["attempts"] += 1
        return False, "invalid_code"
    del login_codes[email_lower]
    return True, "success"

def send_login_email(to_email: str, code: str, language: str = "en") -> bool:
    """Send login verification code via email."""
    return send_email_with_code(to_email, code, language, "login")

async def send_login_email_async(to_email: str, code: str, language: str = "en") -> bool:
    """Async variant for FastAPI endpoints."""
    return await send_email_with_code_async(to_email, code, language, "login")

def send_email_with_code(to_email: str, code: str, language: str = "en", email_type: str = "reset") -> bool:
    """Send email with code (reset or verification) - tries Resend first, then SMTP"""

    # v2.3.x: user request — all code emails MUST be in English regardless of
    # the account's UI language. Sender name is also English ("Support GRAM CITY").
    language = "en"

    # Email content based on type and language
    if email_type == "verification":
        subjects = {
            "en": "Email Verification Code - GRAM City Builder",
            "ru": "Код подтверждения email - GRAM City Builder",
            "zh": "邮箱验证码 - GRAM City Builder"
        }
        bodies = {
            "en": f"""
    <div style="padding: 30px;">
        <div style="text-align: center; margin-bottom: 25px;">
            <h1 style="color: #00ffff; margin: 0; font-size: 28px;">🏙️ GRAM City Builder</h1>
        </div>
        <p style="font-size: 16px; line-height: 1.6; margin-bottom: 20px;">Welcome! Please verify your email with the code below:</p>
        <div style="background: linear-gradient(135deg, rgba(0,255,255,0.15) 0%, rgba(0,200,255,0.1) 100%); border-radius: 12px; padding: 25px; text-align: center; margin: 25px 0; border: 2px solid rgba(0,255,255,0.3);">
            <p style="color: #888; font-size: 12px; margin: 0 0 10px 0; text-transform: uppercase; letter-spacing: 2px;">Your verification code</p>
            <div style="font-size: 42px; font-weight: bold; letter-spacing: 12px; color: #00ffff; font-family: 'Courier New', monospace; text-shadow: 0 0 20px rgba(0,255,255,0.5);">{code}</div>
        </div>
        <p style="color: #888; font-size: 14px;">⏰ This code will expire in <strong>15 minutes</strong>.</p>
        <p style="color: #666; font-size: 13px; margin-top: 20px;">If you didn't register, please ignore this email.</p>
    </div>
""",
            "ru": f"""
    <div style="padding: 30px;">
        <div style="text-align: center; margin-bottom: 25px;">
            <h1 style="color: #00ffff; margin: 0; font-size: 28px;">🏙️ GRAM City Builder</h1>
        </div>
        <p style="font-size: 16px; line-height: 1.6; margin-bottom: 20px;">Добро пожаловать! Подтвердите ваш email с помощью кода ниже:</p>
        <div style="background: linear-gradient(135deg, rgba(0,255,255,0.15) 0%, rgba(0,200,255,0.1) 100%); border-radius: 12px; padding: 25px; text-align: center; margin: 25px 0; border: 2px solid rgba(0,255,255,0.3);">
            <p style="color: #888; font-size: 12px; margin: 0 0 10px 0; text-transform: uppercase; letter-spacing: 2px;">Ваш код подтверждения</p>
            <div style="font-size: 42px; font-weight: bold; letter-spacing: 12px; color: #00ffff; font-family: 'Courier New', monospace; text-shadow: 0 0 20px rgba(0,255,255,0.5);">{code}</div>
        </div>
        <p style="color: #888; font-size: 14px;">⏰ Код действителен <strong>15 минут</strong>.</p>
        <p style="color: #666; font-size: 13px; margin-top: 20px;">Если вы не регистрировались, проигнорируйте это письмо.</p>
    </div>
"""
        }
    elif email_type == "login":
        subjects = {
            "en": "Login Verification Code - GRAM City Builder",
            "ru": "Код подтверждения входа - GRAM City Builder",
        }
        bodies = {
            "en": f"""
    <div style="padding: 30px;">
        <div style="text-align: center; margin-bottom: 25px;">
            <h1 style="color: #00ffff; margin: 0; font-size: 28px;">🏙️ GRAM City Builder</h1>
        </div>
        <p style="font-size: 16px; line-height: 1.6; margin-bottom: 20px;">🔐 Sign-in confirmation. Enter the code below to finish logging in:</p>
        <div style="background: linear-gradient(135deg, rgba(0,255,255,0.15) 0%, rgba(0,200,255,0.1) 100%); border-radius: 12px; padding: 25px; text-align: center; margin: 25px 0; border: 2px solid rgba(0,255,255,0.3);">
            <p style="color: #888; font-size: 12px; margin: 0 0 10px 0; text-transform: uppercase; letter-spacing: 2px;">Your login code</p>
            <div style="font-size: 42px; font-weight: bold; letter-spacing: 12px; color: #00ffff; font-family: 'Courier New', monospace; text-shadow: 0 0 20px rgba(0,255,255,0.5);">{code}</div>
        </div>
        <p style="color: #888; font-size: 14px;">⏰ This code will expire in <strong>15 minutes</strong>.</p>
        <p style="color: #ff6b6b; font-size: 13px; margin-top: 20px;">⚠️ If this wasn't you, change your password immediately.</p>
    </div>
""",
            "ru": f"""
    <div style="padding: 30px;">
        <div style="text-align: center; margin-bottom: 25px;">
            <h1 style="color: #00ffff; margin: 0; font-size: 28px;">🏙️ GRAM City Builder</h1>
        </div>
        <p style="font-size: 16px; line-height: 1.6; margin-bottom: 20px;">🔐 Подтверждение входа. Введите код ниже, чтобы завершить авторизацию:</p>
        <div style="background: linear-gradient(135deg, rgba(0,255,255,0.15) 0%, rgba(0,200,255,0.1) 100%); border-radius: 12px; padding: 25px; text-align: center; margin: 25px 0; border: 2px solid rgba(0,255,255,0.3);">
            <p style="color: #888; font-size: 12px; margin: 0 0 10px 0; text-transform: uppercase; letter-spacing: 2px;">Ваш код входа</p>
            <div style="font-size: 42px; font-weight: bold; letter-spacing: 12px; color: #00ffff; font-family: 'Courier New', monospace; text-shadow: 0 0 20px rgba(0,255,255,0.5);">{code}</div>
        </div>
        <p style="color: #888; font-size: 14px;">⏰ Код действителен <strong>15 минут</strong>.</p>
        <p style="color: #ff6b6b; font-size: 13px; margin-top: 20px;">⚠️ Если это были не вы — немедленно смените пароль.</p>
    </div>
"""
        }
    else:
        # Password reset / 2FA disable
        if email_type == "2fa_disable":
            subjects = {
                "en": "2FA Disable Code - GRAM City Builder",
                "ru": "Код отключения 2FA - GRAM City Builder",
            }
        else:
            subjects = {
                "en": "Password Reset Code - GRAM City Builder",
                "ru": "Код восстановления пароля - GRAM City Builder",
                "zh": "密码重置代码 - GRAM City Builder",
                "es": "Código de restablecimiento de contraseña - GRAM City Builder",
                "de": "Passwort-Reset-Code - GRAM City Builder",
                "fr": "Code de réinitialisation du mot de passe - GRAM City Builder",
                "ja": "パスワードリセットコード - GRAM City Builder",
                "ko": "비밀번호 재설정 코드 - GRAM City Builder"
            }
        
        purpose_text = "отключения 2FA" if email_type == "2fa_disable" else "сброса пароля"
        purpose_text_en = "2FA disable" if email_type == "2fa_disable" else "password reset"
        purpose_icon = "🔐" if email_type == "2fa_disable" else "🔑"
        
        bodies = {
            "en": f"""
    <div style="padding: 30px;">
        <div style="text-align: center; margin-bottom: 25px;">
            <h1 style="color: #00ffff; margin: 0; font-size: 28px;">🏙️ GRAM City Builder</h1>
        </div>
        <p style="font-size: 16px; line-height: 1.6; margin-bottom: 20px;">{purpose_icon} You requested a <strong>{purpose_text_en}</strong>. Use the code below:</p>
        <div style="background: linear-gradient(135deg, rgba(255,165,0,0.15) 0%, rgba(255,100,0,0.1) 100%); border-radius: 12px; padding: 25px; text-align: center; margin: 25px 0; border: 2px solid rgba(255,165,0,0.3);">
            <p style="color: #888; font-size: 12px; margin: 0 0 10px 0; text-transform: uppercase; letter-spacing: 2px;">Your security code</p>
            <div style="font-size: 42px; font-weight: bold; letter-spacing: 12px; color: #ffa500; font-family: 'Courier New', monospace; text-shadow: 0 0 20px rgba(255,165,0,0.5);">{code}</div>
        </div>
        <p style="color: #888; font-size: 14px;">⏰ This code will expire in <strong>15 minutes</strong>.</p>
        <p style="color: #ff6b6b; font-size: 13px; margin-top: 20px;">⚠️ If you didn't request this, someone may be trying to access your account.</p>
    </div>
""",
            "ru": f"""
    <div style="padding: 30px;">
        <div style="text-align: center; margin-bottom: 25px;">
            <h1 style="color: #00ffff; margin: 0; font-size: 28px;">🏙️ GRAM City Builder</h1>
        </div>
        <p style="font-size: 16px; line-height: 1.6; margin-bottom: 20px;">{purpose_icon} Вы запросили код для <strong>{purpose_text}</strong>. Используйте код ниже:</p>
        <div style="background: linear-gradient(135deg, rgba(255,165,0,0.15) 0%, rgba(255,100,0,0.1) 100%); border-radius: 12px; padding: 25px; text-align: center; margin: 25px 0; border: 2px solid rgba(255,165,0,0.3);">
            <p style="color: #888; font-size: 12px; margin: 0 0 10px 0; text-transform: uppercase; letter-spacing: 2px;">Ваш код безопасности</p>
            <div style="font-size: 42px; font-weight: bold; letter-spacing: 12px; color: #ffa500; font-family: 'Courier New', monospace; text-shadow: 0 0 20px rgba(255,165,0,0.5);">{code}</div>
        </div>
        <p style="color: #888; font-size: 14px;">⏰ Код действителен <strong>15 минут</strong>.</p>
        <p style="color: #ff6b6b; font-size: 13px; margin-top: 20px;">⚠️ Если вы не запрашивали это, возможно кто-то пытается получить доступ к вашему аккаунту.</p>
    </div>
"""
        }
    
    subject = subjects.get(language, subjects["en"])
    body = bodies.get(language, bodies["en"])
    
    # Try Resend first (async - run in event loop)
    if RESEND_AVAILABLE and RESEND_API_KEY:
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If already in async context, create task
                future = asyncio.ensure_future(send_email_via_resend(to_email, subject, body))
                # Can't await here in sync function, try SMTP as fallback
            else:
                result = loop.run_until_complete(send_email_via_resend(to_email, subject, body))
                if result:
                    return True
        except RuntimeError:
            # No event loop, try sync approach
            try:
                params = {
                    "from": SENDER_EMAIL,
                    "to": [to_email],
                    "subject": subject,
                    "html": body
                }
                email_result = resend.Emails.send(params)
                logger.info(f"Email sent via Resend (sync) to {to_email}")
                return True
            except Exception as e:
                logger.warning(f"Resend sync failed: {e}, falling back to SMTP")
    
    # Fallback to SMTP
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    from_email = os.environ.get("SMTP_FROM_EMAIL", smtp_user)
    from_name = os.environ.get("SMTP_FROM_NAME", "GRAM City Builder")
    
    if not smtp_user or not smtp_password:
        logger.error("SMTP credentials not configured and Resend unavailable")
        return False
    
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{from_name} <{from_email}>"
        msg["To"] = to_email
        
        html_part = MIMEText(body, "html")
        msg.attach(html_part)
        
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(from_email, to_email, msg.as_string())
        
        logger.info(f"Email sent via SMTP to {to_email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


# Async version for use in FastAPI endpoints
async def send_email_with_code_async(to_email: str, code: str, language: str = "en", email_type: str = "reset") -> bool:
    """Async version - send email with code using Resend (preferred) or SMTP"""

    # v2.3.x: user request — code emails are ALWAYS in English.
    language = "en"

    # Build email content
    if email_type == "verification":
        subject = "Код подтверждения email - GRAM City" if language == "ru" else "Email Verification Code - GRAM City"
    elif email_type == "2fa_disable":
        subject = "Код отключения 2FA - GRAM City" if language == "ru" else "2FA Disable Code - GRAM City"
    elif email_type == "login":
        subject = "Код подтверждения входа - GRAM City" if language == "ru" else "Login Verification Code - GRAM City"
    else:
        subject = "Код восстановления пароля - GRAM City" if language == "ru" else "Password Reset Code - GRAM City"
    
    purpose_map = {
        "verification": ("подтверждения email", "email verification"),
        "2fa_disable": ("отключения 2FA", "2FA disable"),
        "login": ("подтверждения входа", "login verification"),
        "reset": ("сброса пароля", "password reset")
    }
    purpose_ru, purpose_en = purpose_map.get(email_type, ("подтверждения", "verification"))
    purpose = purpose_ru if language == "ru" else purpose_en
    
    html_content = f"""
    <div style="padding: 28px 20px; font-family: Arial, sans-serif; color: #ffffff;">
        <h1 style="color: #00ffff; margin: 0 0 16px 0; font-size: 24px;">GRAM City</h1>
        <p style="margin: 0 0 16px 0; font-size: 15px; line-height: 1.5;">{'Ваш код для ' + purpose + ':' if language == 'ru' else 'Your code for ' + purpose + ':'}</p>
        <div style="background: rgba(0,255,255,0.1); border-radius: 8px; padding: 18px 10px; text-align: center; margin: 18px 0;">
            <span style="display: inline-block; white-space: nowrap; font-size: 34px; font-weight: bold; letter-spacing: 7px; color: #00ffff; font-family: 'Courier New', monospace;">{code}</span>
        </div>
        <p style="color: #888; margin: 0 0 8px 0; font-size: 14px;">{'Код действителен 10 минут.' if language == 'ru' else 'Code valid for 10 minutes.'}</p>
        <p style="color: #f59e0b; font-size: 12px; margin: 0;">{'Если вы не запрашивали код, проигнорируйте это письмо.' if language == 'ru' else "If you didn't request this, ignore this email."}</p>
    </div>
    """
    
    # Try Resend first
    if RESEND_AVAILABLE and RESEND_API_KEY:
        result = await send_email_via_resend(to_email, subject, html_content)
        if result:
            return True
        logger.warning("[email] Resend path failed for %s (type=%s) — falling back to SMTP",
                       _mask_email(to_email), email_type)
    
    # Fallback to sync SMTP in thread
    return await asyncio.to_thread(send_email_with_code, to_email, code, language, email_type)
