from app.agents.data_collection.agent import DataCollectionAgent
from app.agents.data_delivery.agent import DataDeliveryAgent
from app.agents.data_evaluation.agent import DataEvaluationAgent
from app.agents.data_preprocessing.agent import DataPreprocessingAgent
from app.agents.data_report.agent import DataReportAgent
from app.agents.data_survey.agent import DataSurveyAgent
from app.agents.registry import AgentRegistry
from app.llm.client import LLMClient
from app.tools.registry import ToolRegistry


def build_agent_registry(
    llm: LLMClient | None = None, tools: ToolRegistry | None = None, preprocessing=None, workflow=None
) -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(DataSurveyAgent(llm, tools, preprocessing=preprocessing, workflow=workflow))
    registry.register(DataCollectionAgent(workflow))
    registry.register(DataPreprocessingAgent(preprocessing, workflow))
    registry.register(DataEvaluationAgent(workflow))
    registry.register(DataReportAgent(workflow))
    registry.register(DataDeliveryAgent(workflow))
    return registry
