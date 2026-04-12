"""Authentication endpoints: login, me, register, logout."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from src.api.auth import (
    TokenUser, create_access_token, get_current_user,
    hash_password, require_role, verify_password,
)
from src.database.connection import get_db
from src.database.seed import init_db

auth_router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str
    password: str
    full_name: str
    role: Literal["analyst", "manager"] = "analyst"


@auth_router.post("/login")
async def login(form: OAuth2PasswordRequestForm = Depends()) -> dict:
    init_db()
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, role, is_active FROM users WHERE username = ?",
            (form.username,),
        ).fetchone()
    if not row or not verify_password(form.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="Usuário inativo")
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), row["id"]),
        )
    token = create_access_token(row["id"], row["username"], row["role"])
    return {"access_token": token, "token_type": "bearer"}


@auth_router.get("/me")
async def me(current_user: TokenUser = Depends(get_current_user)) -> dict:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, username, full_name, role, created_at, last_login FROM users WHERE id = ?",
            (current_user.user_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return dict(row)


@auth_router.post("/register", status_code=201)
async def register(
    body: RegisterRequest,
    _: TokenUser = Depends(require_role("manager")),
) -> dict:
    init_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, full_name, role, created_at) VALUES (?,?,?,?,?)",
                (body.username, hash_password(body.password), body.full_name, body.role, now),
            )
        return {"ok": True}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Nome de usuário já existe")


@auth_router.post("/logout")
async def logout(_: TokenUser = Depends(get_current_user)) -> dict:
    return {"message": "Logout realizado. Remova o token do cliente."}
