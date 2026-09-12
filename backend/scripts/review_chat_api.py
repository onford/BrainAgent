"""Configured-model, formal chat API check for missing-upstream stage handling."""
import argparse
import asyncio
from pathlib import Path

import httpx

from app.core.config import Settings
from app.main import create_app
from app.search.io import write


async def main(args):
    root, config = Path(args.output).resolve(), Path(args.config).resolve()
    if root.exists() or not config.is_file():
        raise ValueError("Fresh output directory and existing project config required")
    root.mkdir(parents=True)
    settings = Settings(_env_file=str(config)).model_copy(update={
        "database_url_override": f"sqlite+aiosqlite:///{(root / 'review.db').as_posix()}",
        "db_create_tables": True, "workflow_root": str(root / "workflows"),
        "preprocessing_root": str(root / "preprocessing"), "log_dir": root / "logs"})
    message = "请调用 data_report agent 检查现在能否生成报告，并根据实际返回说明缺口。当前没有提供 workflow_id，也没有任何上游运行结果；不能编造已完成的调研、预处理或评价。"
    write(root / "design.json", {"entry": "POST /api/sessions then POST /api/chat; full create_app lifespan",
        "model": settings.llm_model, "provider": settings.llm_base_url, "request": message,
        "scope": "Real-model missing-upstream regression only; no numerical or literature acceptance", "dependency_overrides": []})
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://brainagent.local", timeout=240) as client:
            session = await client.post("/api/sessions")
            session.raise_for_status()
            response = await client.post("/api/chat", json={"session_id": session.json()["id"], "message": message})
            response.raise_for_status()
            value = response.json()
            write(root / "response.json", value)
            steps = value.get("plan", {}).get("steps", [])
            write(root / "result.json", {"http_status": response.status_code, "conversation_status": value["status"],
                "steps": steps, "final_answer": value.get("final_answer"),
                "blocked_stage_observed": any(s["agent"] == "data_report" and s["status"] == "blocked" for s in steps),
                "numerical_acceptance": False})
            print("recorded formal chat response", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", required=True)
    asyncio.run(main(parser.parse_args()))
