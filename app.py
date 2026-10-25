from __future__ import annotations

import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.getenv("LINKS_DATABASE", BASE_DIR / "links.db"))
ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
app = FastAPI(title="Shortlink", description="Create and track short links.")


def connect_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_db() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect_db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS links (
                code TEXT PRIMARY KEY,
                original_url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                click_count INTEGER NOT NULL DEFAULT 0,
                last_clicked_at TEXT
            )
            """
        )


initialize_db()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


class CreateLinkRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    alias: str | None = None
    expires_at: datetime | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip()
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or any(character.isspace() for character in value)
            or parts.username is not None
            or parts.password is not None
        ):
            raise ValueError("Enter a valid http or https URL.")
        try:
            parts.port
        except ValueError as error:
            raise ValueError("Enter a valid http or https URL.") from error
        return value

    @field_validator("alias")
    @classmethod
    def validate_alias(cls, value: str | None) -> str | None:
        if value is not None and not ALIAS_PATTERN.fullmatch(value):
            raise ValueError(
                "Alias must be 3-32 characters using letters, numbers, hyphens, or underscores."
            )
        return value

    @field_validator("expires_at")
    @classmethod
    def validate_expiry(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            comparable = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
            if comparable <= utc_now():
                raise ValueError("Expiry must be a future date and time.")
        return value


@app.get("/", include_in_schema=False)
def homepage() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html")


@app.post("/links", status_code=201)
def create_link(request: CreateLinkRequest) -> dict[str, str | None]:
    code = request.alias or secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]
    expires_at = to_utc_iso(request.expires_at) if request.expires_at else None
    try:
        with connect_db() as connection:
            connection.execute(
                """
                INSERT INTO links (code, original_url, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (code, request.url, to_utc_iso(utc_now()), expires_at),
            )
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail=f"The alias '{code}' is already in use. Please choose another.",
        ) from error

    return {
        "code": code,
        "short_url": f"/{code}",
        "original_url": request.url,
        "expires_at": expires_at,
    }


@app.get("/links/{code}/stats")
def link_stats(code: str) -> dict[str, int | str | None]:
    with connect_db() as connection:
        row = connection.execute(
            "SELECT click_count, last_clicked_at FROM links WHERE code = ?", (code,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Short link not found.")
    return {
        "code": code,
        "total_clicks": row["click_count"],
        "last_clicked_at": row["last_clicked_at"],
    }


@app.get("/{code}")
def redirect_link(code: str) -> RedirectResponse:
    with connect_db() as connection:
        row = connection.execute(
            "SELECT original_url, expires_at FROM links WHERE code = ?", (code,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Short link not found.")
        if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) <= utc_now():
            raise HTTPException(status_code=410, detail="This short link has expired.")
        clicked_at = to_utc_iso(utc_now())
        connection.execute(
            """
            UPDATE links
            SET click_count = click_count + 1, last_clicked_at = ?
            WHERE code = ?
            """,
            (clicked_at, code),
        )
    return RedirectResponse(url=row["original_url"], status_code=302)
