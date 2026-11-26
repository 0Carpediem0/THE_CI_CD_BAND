# -*- coding: utf-8 -*-
"""Клиент для локального стенда http://127.0.0.1:8080."""
import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request

urllib.request.install_opener(
    urllib.request.build_opener(urllib.request.ProxyHandler({}))
)


def parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument(
        "--base",
        default=os.environ.get("STAND_URL", "http://127.0.0.1:8080"),
    )
    return p


def check_local(base: str) -> str:
    host = urllib.parse.urlparse(base).hostname
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit(f"только локальный стенд, получен {host}")
    return base.rstrip("/")


class Client:
    def __init__(self, base: str):
        self.base = check_local(base)

    def call(self, method, path, token=None, body=None, raw=None, content_type=None, timeout=20):
        url = self.base + path
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        elif body is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Token {token}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                blob = resp.read()
                status = resp.status
        except urllib.error.HTTPError as e:
            blob = e.read()
            status = e.code
        parsed = None
        if blob:
            try:
                parsed = json.loads(blob.decode())
            except (UnicodeDecodeError, json.JSONDecodeError):
                parsed = None
        return status, parsed, blob

    def register(self, username, email, password):
        status, data, blob = self.call(
            "POST",
            "/api/users",
            body={"user": {"username": username, "email": email, "password": password}},
        )
        if status not in (200, 201) or not data:
            raise SystemExit(f"регистрация {email} не удалась: {status} {blob[:300]!r}")
        return data["user"]["token"]

    def token_of(self, email, password):
        status, data, blob = self.call(
            "POST",
            "/api/users/login",
            body={"user": {"email": email, "password": password}},
        )
        if status != 200 or not data or "token" not in data.get("user", {}):
            raise SystemExit(f"вход {email} не удался: {status} {blob[:300]!r}")
        return data["user"]["token"]

    def promote(self, token, username, email, password):
        status, data, blob = self.call(
            "PUT",
            "/api/user",
            token=token,
            body={"user": {"username": username, "email": email, "password": password, "role": "moderator"}},
        )
        if status != 200 or not data or data["user"]["role"] != "moderator":
            raise SystemExit(f"роль не сменилась: {status} {blob[:300]!r}")
        return data["user"]["token"]
