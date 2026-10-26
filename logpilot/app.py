import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config, ollama, prompts
from .elastic import ElasticStore
from .storage import LogStore


def default_store():
    if config.ELASTICSEARCH_URL:
        return ElasticStore(config.ELASTICSEARCH_URL, config.JSON_LOG_PATH)
    return LogStore(config.DB_PATH, config.JSON_LOG_PATH)


def create_app(store=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = store or default_store()
        print("LogPilot server started", flush=True)
        yield
        app.state.store.close()

    app = FastAPI(title="LogPilot", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST", "OPTIONS"],
                       allow_headers=["Content-Type"])

    def log(request: Request, status: int, level: str, message: str):
        request.app.state.store.write(
            config.SERVICE_NAME, level, message, request.method, request.url.path, status
        )

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        try:
            html = (config.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        except OSError as exc:
            print(f"Dashboard error: {exc}", flush=True)
            return JSONResponse({"error": "Could not load public/index.html"}, status_code=500)
        log(request, 200, "INFO", "Dashboard opened")
        return HTMLResponse(html)

    @app.get("/error")
    def simulated_error(request: Request):
        log(request, 500, "ERROR", "Simulated internal server error")
        return JSONResponse({"error": "Internal Server Error"}, status_code=500)

    @app.get("/api/stats")
    def stats(request: Request):
        try:
            return request.app.state.store.stats()
        except Exception as exc:
            return JSONResponse({"error": "Could not fetch dashboard statistics", "details": str(exc)}, 500)

    @app.get("/api/errors")
    def errors(request: Request):
        try:
            found = request.app.state.store.recent_errors(20)
            return {"count": len(found), "errors": found}
        except Exception as exc:
            return JSONResponse({"error": "Could not fetch recent errors", "details": str(exc)}, 500)

    @app.post("/ai")
    async def ask(request: Request):
        try:
            raw = await request.body()
            if len(raw) > 10000:
                raise ValueError("Request body too large")
            question = json.loads(raw).get("question")
            if not isinstance(question, str) or not question.strip():
                return JSONResponse({"error": "Please provide a question"}, status_code=400)
            answer = await ollama.chat(prompts.ASSISTANT_SYSTEM, question)
            log(request, 200, "INFO", "AI question answered")
            return {"answer": answer}
        except Exception as exc:
            log(request, 502, "ERROR", "AI request failed")
            return JSONResponse(
                {"error": "Could not get a response from Ollama", "details": str(exc)}, status_code=502
            )

    @app.post("/ai/analyze")
    async def analyze(request: Request):
        try:
            found = request.app.state.store.recent_errors(20)
            question = (prompts.ANALYZE_WITH_ERRORS + json.dumps(found)) if found else prompts.ANALYZE_NO_ERRORS
            analysis = await ollama.chat(prompts.ANALYZER_SYSTEM, question)
            log(request, 200, "INFO", "Log errors analyzed by AI")
            return {"count": len(found), "errors": found, "analysis": analysis}
        except Exception as exc:
            print(f"Analysis error: {exc}", flush=True)
            log(request, 502, "ERROR", "Error analysis failed")
            return JSONResponse({"error": "Could not analyze logs", "details": str(exc)}, status_code=502)

    @app.exception_handler(StarletteHTTPException)
    async def http_exc(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            log(request, 404, "WARN", "Route not found")
            return JSONResponse({"error": "Route not found"}, status_code=404)
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    return app


app = create_app()
