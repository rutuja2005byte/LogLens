import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Where the SQLite database and the JSON log file are stored.
DATA_DIR = Path(os.environ.get("LOGPILOT_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "logpilot.db"
JSON_LOG_PATH = DATA_DIR / "app.json"

# Set ELASTICSEARCH_URL to use the ELK stack (Logstash ships app.json -> Elasticsearch).
# If unset, a built-in SQLite store is used so the app also runs without Docker.
ELASTICSEARCH_URL = os.environ.get("ELASTICSEARCH_URL", "")

PUBLIC_DIR = BASE_DIR / "public"

# Ollama runs on the host machine (not a Python dependency); only its HTTP API is used.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:latest")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "120"))

SERVICE_NAME = "logpilot-api"
