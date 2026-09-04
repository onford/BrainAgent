from app.agents.data_collection.agent import DataCollectionAgent
from app.agents.data_delivery.agent import DataDeliveryAgent
from app.agents.data_evaluation.agent import DataEvaluationAgent
from app.agents.data_preprocessing.agent import DataPreprocessingAgent
from app.agents.data_report.agent import DataReportAgent
from app.agents.data_survey.agent import DataSurveyAgent
from app.agents.registry import AgentRegistry


def build_agent_registry() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(DataSurveyAgent())
    registry.register(DataCollectionAgent())
    registry.register(DataPreprocessingAgent())
    registry.register(DataEvaluationAgent())
    registry.register(DataReportAgent())
    registry.register(DataDeliveryAgent())
    return registry
