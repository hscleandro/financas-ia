"""Autenticação simples para a interface web.

V1 usa senha mestre configurada em WEB_AUTH_PASSWORD. O usuário logado é
mapeado para o primeiro usuário ativo do banco (geralmente o único).
"""
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from config import settings
from database.setup import get_connection
from database.user_setup import get_user_by_telegram_id

security = HTTPBasic(auto_error=False)


def check_password(password: str) -> bool:
    """Verifica se a senha informada corresponde à senha mestre."""
    if not settings.web_auth_password:
        return False
    if not password:
        return False
    return secrets.compare_digest(password, settings.web_auth_password)


def get_current_user(request: Request) -> dict:
    """Retorna o usuário atual a partir da sessão ou autenticação básica."""
    # Tenta sessão primeiro
    user_id = request.session.get("user_id")
    if user_id:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id, telegram_id, name, is_active FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if row and row["is_active"]:
                return dict(row)
        finally:
            conn.close()

    # Fallback para HTTP Basic Auth
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        import base64
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
            if secrets.compare_digest(password, settings.web_auth_password):
                return _resolve_default_user()
        except Exception:
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Autenticação necessária",
        headers={"WWW-Authenticate": "Basic"},
    )


def _resolve_default_user() -> dict:
    """Retorna o primeiro usuário ativo do banco."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, telegram_id, name, is_active FROM users WHERE is_active = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Nenhum usuário ativo encontrado. Execute setup_telegram_user.py primeiro.",
            )
        return dict(row)
    finally:
        conn.close()
