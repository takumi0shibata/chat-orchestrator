import asyncio
import json
import stat
import time
from types import SimpleNamespace as NS
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.chatgpt_auth import ChatGPTAuth, ISSUER, JWKS, RESOURCE, TOKEN
from app.chatgpt_client import ChatGPTClient, ChatGPTStream, completed_response, response_text
from app.config import Settings
from app.model_catalog import MODELS
from test_agent import Client, FakeSandbox, Stream, message, setup


def credentials(**changes):
    return dict(client_id="oaiapp_test", subject="subject-one", email="test@example.com",
                access_token="test-access-token", refresh_token="test-refresh-token",
                expires_at=time.time() + 3600, scopes=["chatgpt.tokens.use.direct"], **changes)


class Listener:
    sockets = [NS(getsockname=lambda: ("127.0.0.1", 14550))]

    def close(self):
        pass

    async def wait_closed(self):
        pass


@pytest.fixture
def no_listener(monkeypatch):
    async def listen(*args, **kwargs):
        assert args[1:3] == ("127.0.0.1", 0)
        return Listener()
    monkeypatch.setattr(asyncio, "start_server", listen)


def test_dynamic_registration_identity_and_private_storage(tmp_path, no_listener):
    async def scenario():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        jwk.update(kid="key-1", alg="RS256")
        calls = []

        def transport(request):
            calls.append(request)
            if str(request.url) == JWKS:
                return httpx.Response(200, json={"keys": [jwk]})
            assert str(request.url) == TOKEN
            body = parse_qs(request.content.decode())
            assert body["client_id"] == ["oaiapp_test"]
            assert body["redirect_uri"] == [auth.pending_uri]
            assert "client_secret" not in body
            token = jwt.encode(dict(iss=ISSUER, sub="subject-one", aud="oaiapp_test",
                                    exp=time.time() + 300, iat=time.time(), nonce=auth.nonce),
                               key, algorithm="RS256", headers={"kid": "key-1"})
            return httpx.Response(200, json=dict(
                access_token="test-access-token", refresh_token="test-refresh-token", id_token=token,
                expires_in=3600, token_type="Bearer", scope="openid chatgpt.tokens.use.direct",
            ))

        auth = ChatGPTAuth(Settings(_env_file=None, data_dir=tmp_path), httpx.MockTransport(transport))
        try:
            result = await auth.begin()
            query = parse_qs(urlsplit(result["authorization_url"]).query)
            assert query["client_id"] == ["dynamic_agent_client"]
            assert query["agent_name_hint"] == ["Agent Chat Orchestrator"]
            assert query["resource"] == [RESOURCE]
            auth.nonce, auth.pending_uri = auth.pending["nonce"], auth.pending["redirect_uri"]
            original_state = auth.pending["state"]
            with pytest.raises(ValueError, match="state"):
                await auth.complete(dict(state="wrong", code="code", client_id="oaiapp_test"))
            assert not calls
            await auth.complete(dict(state=original_state, code="code", client_id="oaiapp_test"))
            assert auth.enabled and auth.status()["login_status"] == "completed"
            assert "test-access-token" not in json.dumps(auth.status())
            assert stat.S_IMODE(auth.path.stat().st_mode) == 0o600
            with pytest.raises(ValueError, match="state"):
                await auth.complete(dict(state=original_state, code="code"))
            host_id = auth.record["host_id"]
            next_query = parse_qs(urlsplit((await auth.begin())["authorization_url"]).query)
            assert next_query["client_id"] == ["oaiapp_test"]
            assert "agent_name_hint" not in next_query
            await auth.logout()
            assert not auth.enabled and not auth.secrets()
            assert auth.record["client_id"] == "oaiapp_test"
            assert auth.record["host_id"] == host_id
            restored = ChatGPTAuth(Settings(_env_file=None, data_dir=tmp_path))
            assert restored.record["host_id"] == host_id
            await restored.close()
        finally:
            await auth.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("claim,value", [("iss", "https://evil.example"), ("aud", "other"),
                                        ("nonce", "wrong"), ("exp", 1), ("sub", "")])
def test_invalid_signed_identity_rejected(tmp_path, claim, value):
    async def scenario():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        jwk.update(kid="key", alg="RS256")
        auth = ChatGPTAuth(Settings(_env_file=None, data_dir=tmp_path), httpx.MockTransport(
            lambda _: httpx.Response(200, json={"keys": [jwk]})))
        claims = dict(iss=ISSUER, sub="subject", aud="oaiapp_test", nonce="nonce",
                      exp=time.time() + 60, iat=time.time())
        claims[claim] = value
        token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "key"})
        try:
            with pytest.raises(ValueError, match="identity"):
                await auth.verify_identity(token, "oaiapp_test", "nonce")
        finally:
            await auth.close()
    asyncio.run(scenario())


def test_refresh_rotation_is_serialized_and_discovery_uses_account_catalog(tmp_path):
    async def scenario():
        calls = []
        def transport(request):
            calls.append(request)
            if request.method == "POST":
                assert parse_qs(request.content.decode())["refresh_token"] == ["test-refresh-token"]
                return httpx.Response(200, json=dict(
                    access_token="rotated", refresh_token="rotated-refresh", expires_in=3600,
                    token_type="Bearer", scope="chatgpt.tokens.use.direct",
                ))
            assert request.headers["authorization"] == "Bearer rotated"
            return httpx.Response(200, json={"models": [
                dict(slug="gpt-6-luna", display_name="Luna for this account", visibility="list"),
                dict(slug="gpt-6-astra", visibility="hidden"),
                dict(slug="unknown-model", visibility="list"),
            ]})
        auth = ChatGPTAuth(Settings(_env_file=None, data_dir=tmp_path), httpx.MockTransport(transport))
        auth.record.update(credentials())
        auth.record["expires_at"] = 0
        try:
            assert await asyncio.gather(auth.access_token(), auth.access_token()) == ["rotated", "rotated"]
            assert len(calls) == 1
            assert auth.record["refresh_token"] == "rotated-refresh"
            assert json.loads(auth.path.read_text())["access_token"] == "rotated"
            models = await auth.models()
            assert [m["id"] for m in models] == ["gpt-6-luna"]
            assert models[0]["label"] == "Luna for this account"
        finally:
            await auth.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("code,cleared", [("invalid_grant", True), ("refresh_token_reused", True), ("server_error", False)])
def test_refresh_failure_revocation_vs_temporary_failure(tmp_path, code, cleared):
    async def scenario():
        auth = ChatGPTAuth(Settings(_env_file=None, data_dir=tmp_path), httpx.MockTransport(
            lambda _: httpx.Response(400 if cleared else 503, json={"error": code})))
        auth.record.update(credentials())
        auth.record["expires_at"] = 0
        try:
            with pytest.raises(ValueError):
                await auth.access_token()
            assert (not auth.enabled) == cleared
            assert bool(auth.secrets()) != cleared
        finally:
            await auth.close()
    asyncio.run(scenario())


def test_identity_without_plan_scope_does_not_enable_inference(tmp_path):
    async def scenario():
        auth = ChatGPTAuth(Settings(_env_file=None, data_dir=tmp_path))
        auth.record.update(credentials())
        auth.record["scopes"] = ["openid"]
        try:
            assert auth.status()["connected"] and not auth.enabled
            with pytest.raises(ValueError, match="plan usage"):
                await auth.access_token()
        finally:
            await auth.close()
    asyncio.run(scenario())


def test_responses_wire_contract_and_native_compact_endpoint(tmp_path):
    async def scenario():
        auth = ChatGPTAuth(Settings(_env_file=None, data_dir=tmp_path))
        auth.record.update(credentials())
        requests = []
        def transport(request):
            requests.append(request)
            assert request.headers["authorization"] == "Bearer test-access-token"
            if request.url.path.endswith("/compact"):
                return httpx.Response(200, json=dict(
                    id="cmp", object="response.compaction", created_at=1,
                    output=[dict(type="compaction", id="item", encrypted_content="ciphertext")],
                    usage=dict(input_tokens=20, output_tokens=5),
                ))
            data = dict(id="resp", object="response", created_at=1, model="gpt-6-luna",
                        status="completed", output=[message()], usage=dict(input_tokens=5, output_tokens=2))
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  text="event: response.completed\ndata: " + json.dumps(dict(type="response.completed", response=data)) + "\n\n")
        client = ChatGPTClient(Settings(_env_file=None, data_dir=tmp_path), auth)
        await client.client.close()
        from openai import AsyncOpenAI
        client.client = AsyncOpenAI(api_key="placeholder", max_retries=0,
                                   http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))
        try:
            stream = await client.create(model="gpt-6-luna", input="hello", max_output_tokens=100,
                                         prompt_cache_key="old", store=True, stream=False)
            await completed_response(stream)
            body = json.loads(requests[0].content)
            assert body["store"] is False and body["stream"] is True
            assert body["input"] == [dict(role="user", content="hello")]
            assert "max_output_tokens" not in body and "prompt_cache_key" not in body
            compacted = await client.compact(model="gpt-6-luna", input=[dict(role="user", content="context")], instructions="Keep facts")
            assert requests[1].url.path == "/v1/responses/compact"
            assert compacted.output[0].type == "compaction"
            assert json.loads(requests[1].content) == dict(model="gpt-6-luna", input=[dict(role="user", content="context")], instructions="Keep facts")
        finally:
            await client.close()
            await auth.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["response.failed", "response.incomplete", "disconnect"])
def test_partial_response_is_never_success(kind):
    class Incomplete:
        closed = False
        async def __aiter__(self):
            yield NS(type="response.output_text.delta", delta="partial")
            if kind != "disconnect":
                yield NS(type=kind)
        async def close(self):
            self.closed = True
    async def scenario():
        stream = Incomplete()
        with pytest.raises(RuntimeError):
            await completed_response(stream)
        assert stream.closed
    asyncio.run(scenario())


def test_stream_retains_completed_text_and_function_calls_in_output_order():
    class Events:
        closed = False
        async def __aiter__(self):
            yield NS(type="response.output_item.done", output_index=1, item=message())
            yield NS(type="response.output_item.done", output_index=0, item=dict(type="function_call", name="shell", call_id="one"))
            yield NS(type="response.completed", response=NS(output=[]))
        async def close(self):
            self.closed = True
    async def scenario():
        events = Events()
        response = await completed_response(ChatGPTStream(events))
        assert response.output[0]["type"] == "function_call"
        assert response_text(response) == "完了"
        assert events.closed
    asyncio.run(scenario())


def test_chatgpt_shell_uses_existing_sandbox_and_paired_history(tmp_path):
    async def scenario():
        call = dict(type="function_call", id="fn", call_id="shell1", name="shell", namespace="workspace",
                    arguments=json.dumps(dict(commands=["printf hello"], timeout_ms=5000)))
        manager, store, fake, request = setup(tmp_path, [[call], [message()]], provider="chatgpt")
        manager.chatgpt_auth.record.update(credentials())
        manager.chatgpt_auth.catalog = [dict(id="gpt-5.6-sol", model="gpt-5.6-sol", **MODELS["gpt-5.6-sol"])]
        try:
            run = manager.start(request)
            await manager.tasks[run["id"]]
            assert store.run(run["id"])["status"] == "completed"
            assert FakeSandbox.instances[-1].commands == ["printf hello"]
            assert fake.calls[0]["tools"][0]["type"] == "namespace"
            assert not any(tool["type"] in ("shell", "apply_patch", "mcp") for tool in fake.calls[0]["tools"])
            output = next(item for item in fake.calls[1]["input"] if item.get("type") == "function_call_output")
            assert output["call_id"] == "shell1"
            assert json.loads(output["output"])[0]["stdout"] == "result"
            events = store.events(run["id"], limit=100000)
            assert any(e["type"] == "command_done" and e["data"]["outcome"]["exit_code"] == 0 for e in events)
            assert store.monthly_costs()  # Only the independent API-key title is charged.
            with store.connect() as db:
                assert db.execute("SELECT COUNT(*) FROM llm_costs WHERE provider='chatgpt'").fetchone()[0] == 0
            request.mcp_ids = ["unsupported"]
            with pytest.raises(ValueError, match="Remote MCP"):
                manager.validate(request)
        finally:
            await manager.shutdown()
    asyncio.run(scenario())


def test_compact_failure_preserves_original_history_no_summary_fallback(tmp_path):
    async def scenario():
        manager, store, fake, request = setup(tmp_path, [[message()]], provider="chatgpt", compact_token_threshold=1000)
        manager.chatgpt_auth.record.update(credentials())
        manager.chatgpt_auth.catalog = [dict(id="gpt-5.6-sol", model="gpt-5.6-sol", **MODELS["gpt-5.6-sol"])]
        original = [dict(role="user", content="Important original context")]
        store.save_context(request.conversation_id, original, "chatgpt", request.model)
        prior = store.create_run(request.model_dump())
        store.event(prior["id"], "response", dict(usage=dict(input_tokens=2000, output_tokens=10)))
        store.save_context(request.conversation_id, original, "chatgpt", request.model, rid=prior["id"])
        store.status(prior["id"], "completed", "Complete")
        async def unsupported(**kwargs):
            raise RuntimeError("subscription_sharing_route_not_supported")
        fake.compact = unsupported
        try:
            run = manager.start(request)
            await manager.tasks[run["id"]]
            assert store.run(run["id"])["status"] == "failed"
            assert original[0] in store.conversation(request.conversation_id)["context"]
            assert not fake.calls
        finally:
            await manager.shutdown()
    asyncio.run(scenario())
