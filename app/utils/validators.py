# app/utils/validators.py
import re
from urllib.parse import urlparse

MX_CP_REGEX = re.compile(r"^\d{5}$")
MX_PHONE_DIGITS = re.compile(r"\D+")

def normalize_phone(s: str) -> str:
    """Normaliza teléfonos: conserva dígitos y agrega +52 si faltan (opcional)."""
    if not s:
        return ""
    digits = MX_PHONE_DIGITS.sub("", s)
    # Si es de 10 dígitos, lo dejamos como 10 o, si quieres, anteponer +52.
    # Para mostrar bonito, lo harás en templates/panel; aquí solo normalizamos.
    return digits

def is_valid_cp(cp: str) -> bool:
    return bool(MX_CP_REGEX.match(cp))

def is_valid_url(url: str) -> bool:
    if not url:
        return False
    try:
        u = urlparse(url)
        return u.scheme in ("http", "https") and bool(u.netloc)
    except Exception:
        return False