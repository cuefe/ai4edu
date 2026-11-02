from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest
from sqlalchemy import select

from app.ai.gateway.config import MOCK, GatewayConfig
from app.ai.gateway.gateway import AIGateway, CallContext
from app.ai.gateway.redact import redact_messages, redact_text
from app.ai.models import AiUsage
from app.core.config import get_settings
from app.core.db import open_session
from app.core.errors import AppError
from tests.conftest import auth, make_platform_admin

CONFIG = """
providers:
  p1: {base_url: http://p1, api_key_env: P1_KEY}
  p2: {base_url: http://p2, api_key_env: P2_KEY}
tiers:
  main:
    - {provider: p1, model: m1, price: {input: 2, output: 8}}
    - {provider: p2, model_env: P2_MODEL}
skills:
  demo: main
"""


class ListSink:
    def __init__(self):
        self.records = []

    async def record(self, rec):
        self.records.append(rec)


def _config(tmp_path: Path, env: dict[str, str]) -> GatewayConfig:
    path = tmp_path / "models.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    config = GatewayConfig.load(path)
    config.env = env
    return config


def _fake_client(behaviour):
    async def create(**kwargs):
        return behaviour(kwargs)

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _completion(text: str, pt: int, ct: int):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct),
    )


def test_candidates_skip_unconfigured_providers(tmp_path):
    config = _config(tmp_path, {"P1_KEY": "k1"})
    assert [(c.provider, c.model) for c in config.candidates("demo")] == [("p1", "m1")]
    config.env = {"P1_KEY": "k1", "P2_KEY": "k2", "P2_MODEL": "m2"}
    assert [(c.provider, c.model) for c in config.candidates("demo")] == [("p1", "m1"), ("p2", "m2")]
    with pytest.raises(KeyError):
        config.candidates("unknown")


def test_shipped_config_is_valid():
    config = GatewayConfig.load(get_settings().ai_config_path)
    assert config.tier_of("tutor") == "fast"


def test_falls_back_to_next_candidate_and_records_usage(tmp_path):
    config = _config(tmp_path, {"P1_KEY": "k1", "P2_KEY": "k2", "P2_MODEL": "m2"})
    sink = ListSink()
    gw = AIGateway(config, sink=sink)
    sent = []

    def p1(_):
        raise RuntimeError("p1 down")

    def p2(kwargs):
        sent.append(kwargs)
        return _completion("你好", 10, 5)

    gw._clients = {"p1": _fake_client(p1), "p2": _fake_client(p2)}
    result = anyio.run(
        lambda: gw.chat("demo", [{"role": "user", "content": "我的电话 13812345678"}], ctx=CallContext())
    )

    assert (result.text, result.provider, result.model) == ("你好", "p2", "m2")
    # 发给模型前去掉了手机号
    assert sent[0]["messages"][0]["content"] == "我的电话 [手机号]"
    assert [(r.candidate.provider, r.ok) for r in sink.records] == [("p1", False), ("p2", True)]
    assert sink.records[1].prompt_tokens == 10
    assert sink.records[1].cost is None  # p2 没配置价格


def test_cost_is_computed_from_price(tmp_path):
    config = _config(tmp_path, {"P1_KEY": "k1"})
    sink = ListSink()
    gw = AIGateway(config, sink=sink)
    gw._clients = {"p1": _fake_client(lambda _: _completion("ok", 1_000_000, 500_000))}
    anyio.run(lambda: gw.chat("demo", [{"role": "user", "content": "hi"}], ctx=CallContext()))
    assert sink.records[0].cost == 2 + 4  # 100 万输入 × 2 元 + 50 万输出 × 8 元


def test_all_candidates_fail(tmp_path):
    config = _config(tmp_path, {"P1_KEY": "k1"})
    gw = AIGateway(config)

    def boom(_):
        raise RuntimeError("down")

    gw._clients = {"p1": _fake_client(boom)}
    with pytest.raises(AppError) as err:
        anyio.run(lambda: gw.chat("demo", [{"role": "user", "content": "hi"}], ctx=CallContext()))
    assert err.value.code == "ai_unavailable"


def test_mock_only_when_allowed(tmp_path):
    config = _config(tmp_path, {})
    assert AIGateway(config, allow_mock=True).candidates("demo") == [MOCK]
    assert AIGateway(config, allow_mock=False).candidates("demo") == []


def test_mock_stream(tmp_path):
    sink = ListSink()
    gw = AIGateway(_config(tmp_path, {}), sink=sink, allow_mock=True)

    async def collect():
        return [
            chunk
            async for chunk in gw.stream(
                "demo", [{"role": "user", "content": "讲讲勾股定理"}], ctx=CallContext()
            )
        ]

    chunks = anyio.run(collect)
    assert "".join(chunks) == "[mock:demo] 讲讲勾股定理"
    assert len(chunks) > 1
    assert sink.records[0].ok and sink.records[0].completion_tokens > 0


def test_redaction():
    assert (
        redact_text("身份证 11010519491231002X，手机 +86 13912345678") == "身份证 [身份证号]，手机 [手机号]"
    )
    assert redact_text("订单号 1381234567890 不是手机号") == "订单号 1381234567890 不是手机号"
    msgs = redact_messages(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "13912345678"},
                    {"type": "image_url", "image_url": {"url": "x"}},
                ],
            }
        ]
    )
    assert msgs[0]["content"][0]["text"] == "[手机号]"
    assert msgs[0]["content"][1]["type"] == "image_url"


def test_ops_ai_endpoints(client):
    make_platform_admin()
    headers = auth(client, "13900000000")

    status = {s["skill"]: s for s in client.get("/api/ops/ai/status", headers=headers).json()}
    assert status["tutor"]["tier"] == "fast"
    assert status["tutor"]["candidates"] == [{"provider": "mock", "model": "mock-echo"}]

    resp = client.post("/api/ops/ai/test", headers=headers, json={"skill": "ping", "prompt": "你好"})
    assert resp.status_code == 200
    assert resp.json()["text"] == "[mock:ping] 你好"

    with open_session(bypass=True) as db:
        assert db.scalars(select(AiUsage.skill)).all() == ["ping"]
    usage = client.get("/api/ops/ai/usage", headers=headers).json()
    assert usage[0]["calls"] == 1 and usage[0]["skill"] == "ping"

    assert (
        client.post("/api/ops/ai/test", headers=headers, json={"skill": "nope", "prompt": "x"}).status_code
        == 400
    )


def test_ops_requires_platform_admin(client):
    from tests.conftest import make_tenant

    make_tenant("t1", "13811110000")
    org_admin = auth(client, "13811110000")
    assert client.get("/api/ops/tenants", headers=org_admin).status_code == 403


def test_ops_create_tenant(client):
    make_platform_admin()
    headers = auth(client, "13900000000")
    body = {
        "code": "School1",
        "name": "一中",
        "kind": "school",
        "admin_name": "校长",
        "admin_phone": "13700000000",
        "admin_password": "admin123",
    }
    assert client.post("/api/ops/tenants", headers=headers, json=body).status_code == 200
    assert client.post("/api/ops/tenants", headers=headers, json=body).status_code == 409
    tenants = client.get("/api/ops/tenants", headers=headers).json()
    assert [(t["code"], t["user_count"]) for t in tenants] == [("school1", 1)]
    assert auth(client, "13700000000")
