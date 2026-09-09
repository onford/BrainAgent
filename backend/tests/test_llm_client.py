import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
import logging

import httpx
from pydantic import BaseModel
import pytest

from app.llm import client as llm
from app.llm.config import LLMConfig


class Answer(BaseModel):
    count: int


def make_client(handler, reasoning_effort=None):
    return llm.OpenAICompatibleClient(
        LLMConfig(
            api_key="private-api-key",
            base_url="https://llm.example/v1",
            model="configured-model",
            reasoning_effort=reasoning_effort,
        ),
        transport=httpx.MockTransport(handler),
    )


def completion(content='{"count": 7}', finish_reason="stop"):
    return httpx.Response(
        200,
        headers={"x-request-id": "completed-request"},
        json={
            "choices": [
                {"message": {"content": content}, "finish_reason": finish_reason}
            ],
            "usage": {"prompt_tokens": 123, "completion_tokens": 45},
        },
    )


@pytest.fixture
def delays(monkeypatch):
    observed = []

    async def sleep(seconds):
        observed.append(seconds)

    monkeypatch.setattr(llm.asyncio, "sleep", sleep)
    return observed


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504, 599])
@pytest.mark.parametrize("reasoning_effort", [None, "max"])
async def test_transient_http_retries_exact_request_then_succeeds(
    delays, status, reasoning_effort
):
    requests = []
    messages = [{"role": "user", "content": "Keep the scientific specification."}]

    def handler(request):
        requests.append(request)
        if len(requests) <= 3:
            return httpx.Response(status, headers={"x-request-id": "retry-request"})
        return completion()

    answer = await make_client(handler, reasoning_effort).structured_output(
        messages, Answer
    )
    assert answer.count == 7
    assert len(requests) == 4 and delays == [1.0, 2.0, 4.0]
    assert all(request.content == requests[0].content for request in requests)
    assert all(request.headers == requests[0].headers for request in requests)
    assert all(
        str(request.url) == "https://llm.example/v1/chat/completions"
        for request in requests
    )
    expected = {
        "model": "configured-model",
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    if reasoning_effort is not None:
        expected["reasoning_effort"] = reasoning_effort
    assert json.loads(requests[0].content) == expected
    assert requests[0].headers["authorization"] == "Bearer private-api-key"


@pytest.mark.parametrize("status", [408, 429, 500, 503])
async def test_http_retry_budget_exhausted_with_locatable_failure(
    delays, status, caplog
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status,
            headers={"x-request-id": f"attempt-{len(requests)}"},
            json={"error": "private-server-body"},
        )

    with caplog.at_level(logging.WARNING, logger="app.llm.calls"):
        with pytest.raises(RuntimeError) as caught:
            await make_client(handler).structured_output(
                [{"role": "user", "content": "private-user-prompt"}], Answer
            )
    assert len(requests) == 4 and delays == [1.0, 2.0, 4.0]
    assert isinstance(caught.value.__cause__, httpx.HTTPStatusError)
    detail = str(caught.value)
    for expected in (
        "model=configured-model",
        "provider=https://llm.example",
        f"status_code={status}",
        "request_id=attempt-4",
        "attempt=4/4",
    ):
        assert expected in detail
    assert caplog.text.count("llm_request_retry") == 3
    for private in ("private-api-key", "private-user-prompt", "private-server-body"):
        assert private not in detail + caplog.text


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 413, 422])
async def test_other_client_errors_do_not_retry_even_with_retry_after(delays, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, headers={"Retry-After": "10", "x-request-id": "bad-request"}
        )

    with pytest.raises(RuntimeError, match=f"status_code={status}") as caught:
        await make_client(handler).chat([])
    assert isinstance(caught.value.__cause__, httpx.HTTPStatusError)
    assert "request_id=bad-request" in str(caught.value)
    assert len(calls) == 1 and delays == []


@pytest.mark.parametrize(
    "error_type",
    [
        httpx.ConnectError,
        httpx.ReadError,
        httpx.WriteError,
        httpx.RemoteProtocolError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
    ],
)
@pytest.mark.parametrize("recover", [True, False])
async def test_connection_and_timeout_errors_use_bounded_retries(
    delays, error_type, recover
):
    calls = []

    def handler(request):
        calls.append(request)
        if recover and len(calls) == 4:
            return completion()
        raise error_type("fixture failure", request=request)

    client = make_client(handler)
    if recover:
        assert (await client.structured_output([], Answer)).count == 7
    else:
        with pytest.raises(RuntimeError) as caught:
            await client.structured_output([], Answer)
        assert isinstance(caught.value.__cause__, error_type)
        assert f"error={error_type.__name__}" in str(caught.value)
        assert "attempt=4/4" in str(caught.value)
        assert "model=configured-model" in str(caught.value)
    assert len(calls) == 4 and delays == [1.0, 2.0, 4.0]
    assert len({request.content for request in calls}) == 1


async def test_mixed_transient_failures_share_one_budget(delays):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) in (1, 3):
            return httpx.Response(429, headers={"x-request-id": "earlier-http-request"})
        raise httpx.ReadTimeout("fixture timeout", request=request)

    with pytest.raises(RuntimeError) as caught:
        await make_client(handler).chat([])
    assert len(calls) == 4 and delays == [1.0, 2.0, 4.0]
    assert "request_id=-" in str(caught.value)
    assert "earlier-http-request" not in str(caught.value)


@pytest.mark.parametrize(
    "retry_after, expected",
    [
        ("7", 7.0),
        ("2.5", 2.5),
        ("3600", 30.0),
        ("0", 1.0),
        ("-10", 1.0),
        ("not a date", 1.0),
        ("NaN", 1.0),
        ("inf", 1.0),
        ("1e999", 1.0),
    ],
)
async def test_retry_after_seconds_are_honored_and_bounded(
    delays, retry_after, expected
):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": retry_after})
        return completion()

    assert (await make_client(handler).structured_output([], Answer)).count == 7
    assert delays == [expected] and len(calls) == 2


@pytest.mark.parametrize("seconds, expected", [(12, 12.0), (3600, 30.0), (-60, 1.0)])
async def test_retry_after_http_date(delays, monkeypatch, seconds, expected):
    now = datetime(2026, 9, 9, 0, 0, 0, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(llm, "datetime", Clock)
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                503,
                headers={
                    "Retry-After": format_datetime(
                        now + timedelta(seconds=seconds), usegmt=True
                    )
                },
            )
        return completion()

    await make_client(handler).chat([])
    assert delays == [expected]


async def test_retry_body_is_frozen_even_if_caller_changes_messages(
    delays, monkeypatch
):
    messages = [{"role": "user", "content": "original request"}]
    bodies = []

    async def sleep(seconds):
        messages[0]["content"] = "changed while awaiting retry"

    monkeypatch.setattr(llm.asyncio, "sleep", sleep)

    def handler(request):
        bodies.append(request.content)
        return httpx.Response(503) if len(bodies) == 1 else completion()

    await make_client(handler).chat(messages)
    assert len(bodies) == 2 and bodies[0] == bodies[1]
    assert json.loads(bodies[1])["messages"][0]["content"] == "original request"


@pytest.mark.parametrize("content", ['{"count":', '{"count": 7}'])
async def test_length_finish_is_capacity_error_even_for_valid_json(
    delays, content, caplog
):
    calls = []

    def handler(request):
        calls.append(request)
        return completion(content, "length")

    with caplog.at_level(logging.INFO, logger="app.llm.calls"):
        with pytest.raises(RuntimeError, match="output/capacity") as caught:
            await make_client(handler).structured_output([], Answer)
    assert not isinstance(caught.value, llm.StructuredOutputError)
    assert "finish_reason=length" in str(caught.value)
    assert "request_id=completed-request" in str(caught.value)
    assert "model=configured-model" in str(caught.value)
    assert "llm_request_completed" not in caplog.text
    assert len(calls) == 1 and delays == []


async def test_truncation_bypasses_workflow_semantic_repair(delays, tmp_path):
    pytest.importorskip("mne")
    pytest.importorskip("mne_bids")
    from tests.workflows.fakes import Reader
    from tests.workflows.test_parallel_research import make_cognition

    calls = []

    def handler(request):
        calls.append(request)
        return completion('{"count":', "length")

    agent = make_cognition(tmp_path, Reader(), make_client(handler))
    with pytest.raises(RuntimeError, match="finish_reason=length"):
        await agent.ask("truncation", Answer, {}, "Return a count.")
    assert len(calls) == 1 and delays == []
    assert [record.status for record in agent.log.records] == ["failed"]


@pytest.mark.parametrize("content", ['{"count":', '{"count": "invalid"}'])
async def test_untruncated_semantic_errors_retain_reply_for_existing_repair(
    delays, content
):
    with pytest.raises(llm.StructuredOutputError) as caught:
        await make_client(lambda _: completion(content)).structured_output([], Answer)
    assert caught.value.content == content
    assert delays == []


@pytest.mark.parametrize(
    "body",
    [
        "not JSON",
        "{}",
        '{"choices": []}',
        '{"choices": [{"message": {"content": null}}]}',
    ],
)
async def test_invalid_http_envelope_is_not_a_model_semantic_error(delays, body):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, text=body, headers={"x-request-id": "bad-envelope"})

    with pytest.raises(RuntimeError, match="invalid response envelope") as caught:
        await make_client(handler).structured_output([], Answer)
    assert "request_id=bad-envelope" in str(caught.value)
    assert len(calls) == 1 and delays == []


@pytest.mark.parametrize("during_backoff", [False, True])
async def test_cancellation_propagates_without_retry(
    delays, monkeypatch, during_backoff
):
    calls = []

    def handler(request):
        calls.append(request)
        if during_backoff:
            return httpx.Response(503)
        raise asyncio.CancelledError()

    async def cancel(seconds):
        raise asyncio.CancelledError()

    monkeypatch.setattr(llm.asyncio, "sleep", cancel)
    with pytest.raises(asyncio.CancelledError):
        await make_client(handler).chat([])
    assert len(calls) == 1


async def test_local_protocol_configuration_error_is_not_retried(delays):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.UnsupportedProtocol("unsupported scheme", request=request)

    with pytest.raises(RuntimeError) as caught:
        await make_client(handler).chat([])
    assert isinstance(caught.value.__cause__, httpx.UnsupportedProtocol)
    assert len(calls) == 1 and delays == []
