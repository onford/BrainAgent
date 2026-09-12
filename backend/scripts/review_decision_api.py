"""Replay one rejected real decision with current schema; never execute it.

This is a live configured-model regression review, not a numerical search or a
replacement for the immutable original request/response/selection.
"""
import argparse
import asyncio
import json
from pathlib import Path

from app.core.config import Settings
from app.llm.client import OpenAICompatibleClient
from app.llm.config import LLMConfig
from app.preprocessing.storage import file_hash
from app.search.contracts import Decision
from app.search.io import read, write
from app.search.reasoning import SYSTEM
from app.search.recipe_contrast import contrasts_to_reference
from scripts.release_workflow_acceptance import hashes


async def main(args):
    if not Path(args.config).is_file():
        raise ValueError("Configured environment file does not exist; refusing implicit model defaults")
    output, search, recorded = Path(args.output), Path(args.search), Path(args.request)
    if output.exists():
        raise ValueError("Use a fresh review directory")
    output.mkdir(parents=True)
    original = read(recorded)
    context = json.loads(next(m["content"] for m in original["messages"] if m["role"] == "user"))
    state = read(search / "search.json")
    # Only static frozen recipe definitions supplement the recorded past input.
    # No later score, candidate outcome or model explanation is copied.
    context["candidate_contrasts_to_reference"] = contrasts_to_reference(state)
    extraction = context["protocol"].get("method_extraction", {})
    for source in extraction.get("sources", []):
        source.pop("recovery", None)
    extraction["recovery_audit"] = {"artifact": "method-extraction.json", "source_id": "protocol:method_extraction",
        "note": "Complete repair prompts/responses remain in the original audit and are available by targeted query."}
    messages = [{"role": "system", "content": SYSTEM + "\nJSON Schema:\n" + json.dumps(Decision.model_json_schema(), ensure_ascii=False)},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)}]
    settings = Settings(_env_file=args.config)
    config = LLMConfig(api_key=settings.llm_api_key, base_url=settings.llm_base_url, model=settings.llm_model,
                       timeout_seconds=settings.llm_timeout_seconds)
    if config.base_url.rstrip("/") == "https://api.deepseek.com":
        config = config.model_copy(update={"reasoning_effort": settings.workflow_reasoning_effort})
    code = Path(__file__).resolve().parents[1] / "app"
    code_hashes = hashes([p for p in code.rglob("*") if p.suffix in {".py", ".json"}], code)
    write(output / "design.json", {"scope": "Configured model API regression of a recorded rejected decision; no numerical execution or commitment",
        "original_request": str(recorded.resolve()), "original_request_sha256": file_hash(recorded),
        "model": config.model, "base_url": config.base_url, "code_hashes": code_hashes,
        "input_changes": ["current system instruction and JSON schema", "static recipe contrasts", "omit repeated repair prompts and responses"],
        "numerical_feedback": "unchanged from original recorded decision"})
    write(output / "request.json", {"messages": messages})
    try:
        decision = await OpenAICompatibleClient(config).structured_output(messages, Decision)
        write(output / "result.json", {"status": "schema_valid", "decision": decision.model_dump(mode="json"),
            "committed": False, "numerical_acceptance": False, "semantic_review_required": True})
        print("schema_valid; review output saved", flush=True)
    except Exception as exc:
        write(output / "result.json", {"status": "failed", "error": f"{type(exc).__name__}: {exc}",
            "rejected_content": getattr(exc, "content", None), "committed": False, "numerical_acceptance": False})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("output", "search", "request", "config"):
        parser.add_argument("--" + name, required=True)
    asyncio.run(main(parser.parse_args()))
