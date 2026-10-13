"""Local SIWC public client. Credentials never cross the UI/agent boundary."""

import asyncio
import base64
import hashlib
import json
import os
import secrets
import tempfile
import time
import uuid
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
AUTHORIZE = ISSUER + "/api/accounts/authorize"
TOKEN = ISSUER + "/api/accounts/oauth/token"
JWKS = ISSUER + "/.well-known/jwks.json"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
TERMINAL_REFRESH_ERRORS = {
    "invalid_grant", "invalid_refresh_token", "token_expired", "refresh_token_expired",
    "refresh_token_invalid", "refresh_token_invalidated", "refresh_token_reused",
}


class ChatGPTAuth:
    def __init__(self, settings, transport=None):
        self.path = settings.data_dir / "chatgpt-auth.json"
        self.record = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.record.setdefault("host_id", "urn:uuid:" + str(uuid.uuid4()))
        self.http = httpx.AsyncClient(
            proxy=settings.outbound_proxy_url, transport=transport, timeout=30,
            follow_redirects=False,
        )
        self.lock = asyncio.Lock()
        self.pending = None
        self.server = None
        self.expiry_task = None
        self.login_status = "idle"
        self.error = None
        self.catalog = []

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".chatgpt-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as file:
                json.dump(self.record, file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)  # mkstemp creates owner-only (0600) files.
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @property
    def enabled(self):
        return bool(self.record.get("access_token") and
                    "chatgpt.tokens.use.direct" in self.record.get("scopes", []))

    def status(self):
        return dict(
            connected=bool(self.record.get("access_token")), plan_usage=self.enabled,
            email=self.record.get("email"), login_status=self.login_status, error=self.error,
        )

    def secrets(self):
        return [self.record[k] for k in ("access_token", "refresh_token", "id_token")
                if self.record.get(k)]

    async def begin(self):
        async with self.lock:
            await self.cancel()
            self.save()
            verifier = secrets.token_urlsafe(64)
            self.server = await asyncio.start_server(self.callback, "127.0.0.1", 0, limit=8192)
            port = self.server.sockets[0].getsockname()[1]
            self.pending = dict(
                state=secrets.token_urlsafe(32), nonce=secrets.token_urlsafe(32),
                verifier=verifier, redirect_uri=f"http://127.0.0.1:{port}/auth/callback",
                expires=time.time() + 600, client_id=self.record.get("client_id"),
            )
            query = dict(
                client_id=self.record.get("client_id") or "dynamic_agent_client",
                ext_agent_host_id=self.record["host_id"], response_type="code",
                redirect_uri=self.pending["redirect_uri"], scope=SCOPES, resource=RESOURCE,
                state=self.pending["state"], nonce=self.pending["nonce"],
                code_challenge_method="S256",
                code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("="),
            )
            if not self.record.get("client_id"):
                query["agent_name_hint"] = "Agent Chat Orchestrator"
            # Use the returning account selector rather than sending an ID-token
            # hint through the React UI. The verified identity must still match.
            self.login_status, self.error = "pending", None
            self.expiry_task = asyncio.create_task(self.expire())
            return dict(authorization_url=AUTHORIZE + "?" + urlencode(query))

    async def expire(self):
        await asyncio.sleep(600)
        if self.pending:
            self.login_status, self.error = "failed", "Sign-in expired. Please try again."
            self.pending = None
            await self.close_listener()

    async def close_listener(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        if self.expiry_task and self.expiry_task is not asyncio.current_task():
            self.expiry_task.cancel()
        self.expiry_task = None

    async def cancel(self):
        self.pending = None
        await self.close_listener()
        if self.login_status == "pending":
            self.login_status = "idle"

    async def callback(self, reader, writer):
        # Separate loopback listener avoids logging OAuth codes in uvicorn access logs
        # and permits browser navigation without exempting the application's APIs.
        status, message = 400, "Sign-in could not be verified. Return to Agent Chat."
        try:
            async with asyncio.timeout(40):
                header = (await reader.readuntil(b"\r\n\r\n")).decode("ascii")
                method, target, _ = header.split("\r\n", 1)[0].split(" ")
                parsed = urlsplit(target)
                headers = {k.lower(): v.strip() for k, v in
                           (line.split(":", 1) for line in header.split("\r\n")[1:] if ":" in line)}
                if (method != "GET" or parsed.path != "/auth/callback" or
                        not self.pending or headers.get("host") != urlsplit(self.pending["redirect_uri"]).netloc):
                    raise ValueError("Invalid callback")
                params = parse_qs(parsed.query)
                if any(len(values) != 1 for values in params.values()):
                    raise ValueError("Ambiguous callback")
                await self.complete({k: v[0] for k, v in params.items()})
                status, message = 200, "ChatGPT connected. You can close this tab and return to Agent Chat."
        except (ValueError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            pass
        finally:
            body = f"<!doctype html><title>Agent Chat</title><p>{message}</p>".encode()
            writer.write(f"HTTP/1.1 {status} {'OK' if status == 200 else 'Bad Request'}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {len(body)}\r\nCache-Control: no-store\r\nReferrer-Policy: no-referrer\r\nContent-Security-Policy: default-src 'none'\r\nConnection: close\r\n\r\n".encode() + body)
            try:
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

    async def complete(self, params):
        async with self.lock:
            pending = self.pending
            if (not pending or time.time() >= pending["expires"] or
                    not secrets.compare_digest(params.get("state", ""), pending["state"])):
                raise ValueError("Invalid or expired sign-in state")
            self.pending = None  # one-time consumption before network calls
            await self.close_listener()
            try:
                if params.get("error") or not params.get("code"):
                    raise ValueError("Sign-in declined or incomplete. Please try again.")
                cid = params.get("client_id") or pending["client_id"]
                if (not cid or cid == "dynamic_agent_client" or
                        (pending["client_id"] and cid != pending["client_id"])):
                    raise ValueError("Unexpected ChatGPT registration")
                # Retain registration even when the code exchange fails.
                self.record["client_id"] = cid
                self.save()
                data = await self.token_request(dict(
                    grant_type="authorization_code", client_id=cid, code=params["code"],
                    code_verifier=pending["verifier"], redirect_uri=pending["redirect_uri"],
                    resource=RESOURCE,
                ))
                identity = await self.verify_identity(data.get("id_token"), cid, pending["nonce"])
                if self.record.get("subject") and identity["sub"] != self.record["subject"]:
                    raise ValueError("Sign in with the previously connected ChatGPT account.")
                self.update_tokens(data)
                self.record.update(subject=identity["sub"], email=identity.get("email"))
                self.save()
                self.catalog = []
                self.login_status, self.error = "completed", None
            except Exception as error:
                self.login_status = "failed"
                self.error = str(error) if isinstance(error, ValueError) else "ChatGPT sign-in failed. Please try again."
                raise ValueError(self.error) from None

    async def verify_identity(self, token, cid, nonce):
        try:
            header = jwt.get_unverified_header(token)
            response = await self.http.get(JWKS)
            response.raise_for_status()
            key = next(k for k in response.json()["keys"] if k.get("kid") == header.get("kid"))
            identity = jwt.decode(
                token, jwt.PyJWK.from_dict(key).key, algorithms=["RS256"],
                audience=cid, issuer=ISSUER, leeway=5,
                options={"require": ["sub", "exp", "iat", "nonce"]},
            )
            if identity["nonce"] != nonce or not isinstance(identity["sub"], str) or not identity["sub"]:
                raise ValueError("Invalid identity")
            return identity
        except Exception:
            raise ValueError("ChatGPT identity could not be verified.") from None

    async def token_request(self, body):
        response = await self.http.post(TOKEN, data=body)
        if response.is_error:
            try:
                error = response.json().get("error")
                code = error.get("code") if isinstance(error, dict) else error
            except ValueError:
                code = None
            if body["grant_type"] == "refresh_token" and code in TERMINAL_REFRESH_ERRORS:
                self.clear_tokens()
                raise ValueError("ChatGPT session expired. Please sign in again.")
            raise ValueError(f"ChatGPT token request failed (HTTP {response.status_code}). Please try again.")
        return response.json()

    def update_tokens(self, data, refresh=False):
        if (not isinstance(data.get("access_token"), str) or not data["access_token"] or
                data.get("token_type", "").lower() != "bearer" or
                not isinstance(data.get("expires_in"), (int, float)) or data["expires_in"] <= 0 or
                (refresh and not data.get("refresh_token"))):
            raise ValueError("Incomplete ChatGPT credentials")
        update = {k: data[k] for k in ("access_token", "refresh_token", "id_token") if data.get(k)}
        update.update(expires_at=time.time() + data["expires_in"],
                      scopes=data.get("scope", " ".join(self.record.get("scopes", [])) if refresh else "").split())
        self.record.update(update)

    async def access_token(self):
        async with self.lock:
            if not self.enabled:
                raise ValueError("Connect ChatGPT and enable ChatGPT plan usage in Settings.")
            if self.record.get("expires_at", 0) <= time.time() + 60:
                if not self.record.get("refresh_token"):
                    self.clear_tokens()
                    raise ValueError("ChatGPT session expired. Please sign in again.")
                data = await self.token_request(dict(
                    grant_type="refresh_token", client_id=self.record["client_id"],
                    refresh_token=self.record["refresh_token"], resource=RESOURCE,
                ))
                self.update_tokens(data, refresh=True)
                self.save()
            return self.record["access_token"]

    async def models(self):
        if not self.enabled:
            self.catalog = []
            return []
        response = await self.http.get(RESOURCE + "/models", headers={
            "Authorization": "Bearer " + await self.access_token(),
        })
        if response.is_error:
            raise ValueError(f"ChatGPT model discovery failed (HTTP {response.status_code}).")
        from app.model_catalog import MODELS
        self.catalog = []
        for model in response.json().get("models", []):
            slug = model.get("slug")
            if model.get("visibility") == "list" and slug in MODELS:
                self.catalog.append(dict(id=slug, model=slug, **{
                    **MODELS[slug], "label": model.get("display_name") or MODELS[slug]["label"],
                }))
        return self.catalog

    def clear_tokens(self):
        for key in ("access_token", "refresh_token", "id_token", "expires_at", "scopes"):
            self.record.pop(key, None)
        self.catalog = []
        self.save()

    async def logout(self):
        async with self.lock:
            await self.cancel()
            self.clear_tokens()
            self.login_status, self.error = "idle", None

    async def close(self):
        await self.cancel()
        await self.http.aclose()
