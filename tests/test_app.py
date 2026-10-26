import pytest
from fastapi.testclient import TestClient

from logpilot import ollama
from logpilot.app import create_app
from logpilot.storage import LogStore


@pytest.fixture
def client(tmp_path):
    store = LogStore(tmp_path / "t.db", tmp_path / "app.json")
    with TestClient(create_app(store)) as c:
        yield c


def test_dashboard_and_stats(client):
    assert client.get("/").status_code == 200
    assert client.get("/error").status_code == 500
    assert client.get("/nope").json() == {"error": "Route not found"}
    s = client.get("/api/stats").json()
    assert s["totalEvents"] == 3 and s["errorEvents"] == 1
    assert s["statusCodes"] == {"200": 1, "500": 1, "404": 1}


def test_errors(client):
    client.get("/error")
    body = client.get("/api/errors").json()
    assert body["count"] == 1
    assert body["errors"][0]["statusCode"] == 500 and body["errors"][0]["url"] == "/error"


def test_ai_validation(client):
    assert client.post("/ai", json={"question": " "}).status_code == 400


def test_ai_and_analyze_with_mock(client, monkeypatch):
    async def fake(system, user):
        return "ok:" + user[:12]
    monkeypatch.setattr(ollama, "chat", fake)
    assert client.post("/ai", json={"question": "why?"}).json() == {"answer": "ok:why?"}
    client.get("/error")
    r = client.post("/ai/analyze").json()
    assert r["count"] == 1 and r["analysis"].startswith("ok:Analyze")


def test_ollama_down_returns_502(client, monkeypatch):
    monkeypatch.setattr("logpilot.config.OLLAMA_URL", "http://127.0.0.1:9")
    assert client.post("/ai/analyze").status_code == 502


def test_elastic_store_queries():
    import httpx
    from logpilot.elastic import ElasticStore
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append((str(req.url), body))
        if body.get("size") == 0:
            return httpx.Response(200, json={"hits": {"total": {"value": 5}}, "aggregations": {
                "status_codes": {"buckets": [{"key": 500, "doc_count": 2}, {"key": 200, "doc_count": 3}]},
                "error_events": {"doc_count": 2}}})
        return httpx.Response(200, json={"hits": {"hits": [{"_source": {"level": "ERROR", "statusCode": 500}}]}})

    import json, tempfile, pathlib
    s = ElasticStore("http://es:9200", pathlib.Path(tempfile.mkdtemp()) / "app.json")
    s._client = httpx.Client(transport=httpx.MockTransport(handler))
    assert s.stats() == {"totalEvents": 5, "errorEvents": 2, "statusCodes": {"500": 2, "200": 3}}
    assert s.recent_errors() == [{"level": "ERROR", "statusCode": 500}]
    assert seen[0][0] == "http://es:9200/logpilot-*/_search"
    assert seen[1][1]["query"]["bool"]["filter"] == [{"term": {"level.keyword": "ERROR"}}]
