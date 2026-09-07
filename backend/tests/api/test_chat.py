from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.fakes import ScriptedLLMClient, delegate, finish, full_workflow_responses

TEST_CREDENTIAL_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


def test_chat_stops_before_evaluation_without_real_preprocessing_inputs(tmp_path: Path) -> None:
    settings = Settings(
        database_url_override=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        brain_agent_credential_encryption_key=TEST_CREDENTIAL_KEY,
    )
    responses = full_workflow_responses()
    responses.insert(
        1,
        {
            "action": "finish",
            "rationale": "测试中无需真实检索",
            "summary": "已完成测试数据集调研。",
        },
    )
    with TestClient(create_app(settings, ScriptedLLMClient(responses))) as client:
        session_response = client.post("/api/sessions")
        assert session_response.status_code == 201
        session_id = session_response.json()["id"]
        response = client.post(
            "/api/chat",
            json={
                "session_id": session_id,
                "message": "请执行 EEG 数据的完整流程",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert [step["agent"] for step in body["plan"]["steps"]] == [
            "data_survey",
            "data_collection",
            "data_preprocessing",
        ]
        assert [result["agent_name"] for result in body["results"]] == [
            "data_survey",
            "data_collection",
            "data_preprocessing",
        ]
        assert body["results"][-1]["output"]["execution_status"] == "needs_input"
        assert body["plan"]["steps"][-1]["status"] == "blocked"
        assert "尚未完成" in body["final_answer"]

        sessions = client.get("/api/sessions")
        assert sessions.status_code == 200
        assert sessions.json()[0]["id"] == session_id
        assert [message["role"] for message in sessions.json()[0]["messages"]] == [
            "user",
            "assistant",
        ]
        assistant = sessions.json()[0]["messages"][-1]
        assert [activity["event_type"] for activity in assistant["activities"]] == [
            event["event_type"] for event in body["events"]
        ]
        assert any(
            activity["event_type"] == "thought"
            for activity in assistant["activities"]
        )
        observation = next(
            activity
            for activity in assistant["activities"]
            if activity["event_type"] == "observation"
        )
        assert observation["data"]["result"]["agent_name"] == "data_survey"


def test_stream_chat_returns_react_events(tmp_path: Path) -> None:
    settings = Settings(
        database_url_override=f"sqlite+aiosqlite:///{tmp_path / 'stream.db'}",
        brain_agent_credential_encryption_key=TEST_CREDENTIAL_KEY,
    )
    llm = ScriptedLLMClient(
        [
            delegate("data_survey", "调研数据集"),
            {
                "action": "finish",
                "rationale": "测试中无需真实检索",
                "summary": "已完成测试数据集调研。",
            },
            delegate("data_report", "生成报告"),
            finish("调研和报告已完成。"),
        ]
    )
    with TestClient(create_app(settings, llm)) as client:
        session_id = client.post("/api/sessions").json()["id"]
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"session_id": session_id, "message": "请调研这个 EEG 数据集并生成报告"},
        ) as response:
            body = "".join(response.iter_text())
        assert response.status_code == 200
        assert '"event_type":"thought"' in body
        assert '"agent_name":"data_survey"' in body
        assert '"agent_name":"data_report"' in body
        assert '"event_type":"stream_completed"' in body

        restored = client.get(f"/api/sessions/{session_id}").json()
        assistant = restored["messages"][-1]
        assert [activity["event_type"] for activity in assistant["activities"]] == [
            "run_started",
            "thought",
            "agent_started",
            "observation",
            "thought",
            "agent_started",
            "observation",
            "thought",
            "run_completed",
        ]
        assert assistant["activities"][3]["agent_name"] == "data_survey"
        assert assistant["activities"][6]["agent_name"] == "data_report"


def test_session_list_is_most_recent_first_and_contains_conversation(tmp_path: Path) -> None:
    settings = Settings(
        database_url_override=f"sqlite+aiosqlite:///{tmp_path / 'sessions.db'}",
        brain_agent_credential_encryption_key=TEST_CREDENTIAL_KEY,
    )
    llm = ScriptedLLMClient([finish("这是第一段对话的回答。")])
    with TestClient(create_app(settings, llm)) as client:
        first_id = client.post("/api/sessions").json()["id"]
        second_id = client.post("/api/sessions").json()["id"]

        response = client.post(
            "/api/chat",
            json={"session_id": first_id, "message": "继续第一段对话"},
        )
        assert response.status_code == 200

        sessions = client.get("/api/sessions").json()
        assert [session["id"] for session in sessions] == [first_id, second_id]
        assert [message["role"] for message in sessions[0]["messages"]] == [
            "user",
            "assistant",
        ]
        assert sessions[0]["messages"][-1]["content"] == "这是第一段对话的回答。"


def test_delete_session_removes_messages_and_returns_404_afterwards(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_url_override=f"sqlite+aiosqlite:///{tmp_path / 'delete-session.db'}",
        brain_agent_credential_encryption_key=TEST_CREDENTIAL_KEY,
    )
    with TestClient(create_app(settings, ScriptedLLMClient([finish("回答")]))) as client:
        session_id = client.post("/api/sessions").json()["id"]
        response = client.post(
            "/api/chat",
            json={"session_id": session_id, "message": "准备删除的消息"},
        )
        assert response.status_code == 200

        deleted = client.delete(f"/api/sessions/{session_id}")

        assert deleted.status_code == 204
        assert client.get(f"/api/sessions/{session_id}").status_code == 404
        assert all(
            session["id"] != session_id
            for session in client.get("/api/sessions").json()
        )


def test_delete_missing_session_returns_404(tmp_path: Path) -> None:
    settings = Settings(
        database_url_override=f"sqlite+aiosqlite:///{tmp_path / 'missing-session.db'}",
        brain_agent_credential_encryption_key=TEST_CREDENTIAL_KEY,
    )
    with TestClient(create_app(settings, ScriptedLLMClient([]))) as client:
        assert client.delete("/api/sessions/missing").status_code == 404
