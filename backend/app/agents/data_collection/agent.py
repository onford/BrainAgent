import asyncio

from app.agents.base import BaseAgent
from app.runtime.context import AgentContext, AgentTask
from app.runtime.result import AgentResult, Artifact


class DataCollectionAgent(BaseAgent):
    name = "data_collection"
    description = "Inspects source data read-only and plans standardized BIDS ingestion."

    async def run(self, task: AgentTask, context: AgentContext) -> AgentResult:
        await asyncio.sleep(0.15)
        output = {
            "mode": "placeholder",
            "source_policy": "read_only",
            "target_standard": {"EEG": "BIDS", "iEEG": "BIDS-iEEG"},
            "ingestion_status": "awaiting_input_root",
            "planned_artifacts": [
                "source-inventory.tsv", "record-index.tsv", "source-to-bids.tsv",
                "bids-ingestion.json", "official-validator.json",
            ],
            "checks": [
                "scope_and_files", "directory_and_naming", "format_readability",
                "subjects_and_groups", "acquisition", "channels", "coordinates",
                "dimensions_units_values", "time_axis", "events", "trials",
                "behavior", "stimulus_sync", "raw_processed_mapping", "exclusions",
            ],
        }
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=output,
            artifacts=[Artifact(name="ingestion_manifest", kind="manifest", data=output)],
            observations=["没有输入目录，因此没有改动或扫描任何源数据。"],
        )
