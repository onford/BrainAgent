"""Probe real public literature APIs and optionally read a returned full-text URL.

Run from backend: python scripts/literature_smoke.py --read-full-text
Uses no stored user credentials. Provider failures remain visible in the JSON report.
Exit status is nonzero if no provider finds papers, or a requested full-text read fails.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.integrations.clients.http import HttpExternalToolClient
from app.integrations.definitions import TOOL_DEFINITION_BY_ID
from app.runtime.context import AgentContext
from app.tools.registry import ToolRegistry
from app.workflows.source_reader import SourceReader, abstract_only


class PublicProviders:
    async def get_client(self, name, context):
        return HttpExternalToolClient(
            TOOL_DEFINITION_BY_ID[name], {}, timeout_seconds=20, max_retries=0
        )


async def run(args):
    registry = ToolRegistry(PublicProviders())
    context = AgentContext(
        owner_id="smoke", session_id="smoke", user_message=args.query
    )

    async def search(name):
        result = await registry.execute(name, context, query=args.query, limit=10)
        return name, result

    results = await asyncio.gather(*(search(name) for name in args.providers))
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "query": args.query,
        "credentials": "anonymous public access",
        "providers": [],
        "reads": [],
    }
    for name, result in results:
        output = result.output or {}
        report["providers"].append(
            {
                "provider": name,
                "success": result.success,
                "result_count": output.get("result_count", 0),
                "total_results": output.get("total_results"),
                "with_abstract": sum(
                    bool(item.get("summary")) for item in output.get("items", [])
                ),
                "with_full_text_url": sum(
                    bool(item.get("full_text_url") or item.get("open_access_pdf"))
                    for item in output.get("items", [])
                ),
                "examples": [
                    {key: item.get(key) for key in ("title", "url", "full_text_url")}
                    for item in output.get("items", [])[:2]
                ],
                "error_code": result.metadata.get("error_code"),
            }
        )
    if args.read_full_text:
        candidates = list(
            dict.fromkeys(
                item.get("full_text_url") or item.get("open_access_pdf")
                for _, result in results
                if result.success
                for item in (result.output or {}).get("items", [])
                if item.get("full_text_url") or item.get("open_access_pdf")
            )
        )
        for url in candidates[:3]:
            try:
                document = await SourceReader().read(url, "paper")
                usable = not abstract_only(document)
                report["reads"].append(
                    {
                        "url": url,
                        "resolved_url": document.url,
                        "success": usable,
                        "characters": len(document.text),
                        "truncated": document.truncated,
                        "sha256": document.sha256,
                    }
                )
                if usable:
                    break
            except Exception as exc:
                report["reads"].append(
                    {"url": url, "success": False, "error_type": type(exc).__name__}
                )
    report["passed"] = any(row["result_count"] for row in report["providers"]) and (
        not args.read_full_text or any(row["success"] for row in report["reads"])
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="EEGMMIDB motor imagery")
    parser.add_argument(
        "--providers",
        nargs="+",
        default=["europe_pmc", "crossref", "openalex", "arxiv", "semantic_scholar"],
        choices=["europe_pmc", "crossref", "openalex", "arxiv", "semantic_scholar"],
    )
    parser.add_argument("--read-full-text", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(run(args))
    rendered = json.dumps(report, ensure_ascii=True, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
