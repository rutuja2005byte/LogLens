"""Elasticsearch-backed store. The app only writes app.json; Logstash ships it to
Elasticsearch, and this class queries it (same queries as the original project)."""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx


class ElasticStore:
    def __init__(self, es_url: str, json_log_path: Path, index_pattern: str = "logpilot-*"):
        self.es_url = es_url.rstrip("/")
        self.index_pattern = index_pattern
        self.json_log_path = Path(json_log_path)
        self.json_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._client = httpx.Client(timeout=15)

    def write(self, service, level, message, method=None, url=None, status_code=None) -> dict:
        event = {
            "@timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "service": service, "level": level, "message": message,
            "method": method, "url": url, "statusCode": status_code,
        }
        line = json.dumps(event)
        with self._lock, open(self.json_log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line, flush=True)
        return event

    def _search(self, body: dict) -> dict:
        r = self._client.post(f"{self.es_url}/{self.index_pattern}/_search", json=body)
        r.raise_for_status()
        return r.json()

    def stats(self) -> dict:
        res = self._search({
            "size": 0,
            "aggs": {
                "status_codes": {"terms": {"field": "statusCode", "size": 10}},
                "error_events": {"filter": {"term": {"level.keyword": "ERROR"}}},
            },
        })
        buckets = res.get("aggregations", {}).get("status_codes", {}).get("buckets", [])
        return {
            "totalEvents": res.get("hits", {}).get("total", {}).get("value", 0),
            "errorEvents": res.get("aggregations", {}).get("error_events", {}).get("doc_count", 0),
            "statusCodes": {str(b["key"]): b["doc_count"] for b in buckets},
        }

    def recent_errors(self, limit: int = 20) -> list[dict]:
        res = self._search({
            "size": limit,
            "query": {"bool": {"filter": [{"term": {"level.keyword": "ERROR"}}]}},
            "sort": [{"@timestamp": "desc"}],
        })
        return [h["_source"] for h in res.get("hits", {}).get("hits", [])]

    def close(self):
        self._client.close()
