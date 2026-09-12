import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.sites_gateway import create_gateway


def test_gateway_requires_a_strong_server_secret(monkeypatch):
    monkeypatch.delenv('BRAIN_AGENT_BACKEND_TOKEN', raising=False)
    with pytest.raises(RuntimeError):
        create_gateway()


def test_gateway_rejects_anonymous_http_and_websocket_visitors(monkeypatch):
    monkeypatch.setenv('BRAIN_AGENT_BACKEND_TOKEN', 'x' * 48)
    with TestClient(create_gateway()) as client:
        assert client.get('/api/sessions').status_code == 401
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/_bridge/chat'):
                pass


def test_gateway_does_not_publish_backend_admin_docs(monkeypatch):
    monkeypatch.setenv('BRAIN_AGENT_BACKEND_TOKEN', 'x' * 48)
    with TestClient(create_gateway()) as client:
        assert client.get('/docs', headers={'Authorization': 'Bearer ' + 'x' * 48}).status_code == 404
