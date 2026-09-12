"""Authenticated local ingress for the public Sites Worker; bind to loopback only."""
import asyncio
import hmac
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask


def create_gateway() -> FastAPI:
    token = os.environ.get("BRAIN_AGENT_BACKEND_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("BRAIN_AGENT_BACKEND_TOKEN must contain at least 32 characters")
    origin = "http://127.0.0.1:8001"

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(600, connect=5)) as client:
            app.state.client = client
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def authorized(headers):
        return hmac.compare_digest(headers.get("authorization", ""), f"Bearer {token}")

    def upstream_headers(headers):
        selected = {k: headers[k] for k in ("accept", "content-type", "range", "if-none-match", "if-modified-since") if k in headers}
        # Always isolate public activity from local-development-user and its saved credentials.
        selected["X-Brain-Agent-Owner-ID"] = "sites-public"
        return selected

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def proxy(path: str, request: Request):
        if not authorized(request.headers):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        if path != "health" and not path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        target = httpx.URL(origin + "/" + path, query=request.url.query.encode())
        try:
            outgoing = request.app.state.client.build_request(request.method, target, headers=upstream_headers(request.headers), content=request.stream())
            response = await request.app.state.client.send(outgoing, stream=True)
        except httpx.HTTPError:
            return JSONResponse({"detail": "Local backend is unavailable"}, status_code=502)
        headers = {k: v for k, v in response.headers.items() if k not in ("connection", "transfer-encoding", "content-encoding", "content-length")}
        return StreamingResponse(response.aiter_bytes(), status_code=response.status_code, headers=headers, background=BackgroundTask(response.aclose))

    @app.websocket("/_bridge/chat")
    async def chat_bridge(websocket: WebSocket):
        if not authorized(websocket.headers):
            await websocket.close(code=1008)
            return
        await websocket.accept()

        async def relay():
            body = await asyncio.wait_for(websocket.receive_text(), timeout=20)
            if len(body.encode()) > 1_048_576:
                await websocket.close(code=1009)
                return
            headers = upstream_headers(websocket.headers)
            headers.update({"Content-Type": "application/json", "Accept": "text/event-stream"})
            async with websocket.app.state.client.stream("POST", origin + "/api/chat/stream", headers=headers, content=body) as response:
                await websocket.send_json({"type": "headers", "status": response.status_code, "contentType": response.headers.get("content-type", "application/json")})
                async for chunk in response.aiter_bytes():
                    await websocket.send_bytes(chunk)
                await websocket.send_json({"type": "end"})
                await websocket.close(code=1000)

        try:
            await relay()
        except WebSocketDisconnect:
            pass
        except (httpx.HTTPError, asyncio.TimeoutError):
            try:
                await websocket.send_json({"type": "error"})
                await websocket.close(code=1011)
            except (WebSocketDisconnect, RuntimeError):
                pass

    return app
