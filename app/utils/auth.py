# app/utils/auth.py
import os
from functools import wraps
from flask import session, redirect, url_for, request

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")  # en producción: hashear

def login_admin(user: str, password: str) -> bool:
    # Por simplicidad comparamos texto plano. En producción recomendamos almacenar hash (bcrypt).
    return user == ADMIN_USER and password == ADMIN_PASSWORD

def require_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin_ok"):
            # redirigimos con next= para volver al destino tras login
            return redirect(url_for("admin.login", next=request.path))
        return f(*args, **kwargs)
    return wrapper