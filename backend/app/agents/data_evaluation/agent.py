from app.workflows.agent import WorkflowAgent


class DataEvaluationAgent(WorkflowAgent):
    name = "data_evaluation"
    description = "Selects a complete preprocessing candidate randomly with a recorded seed; quality ranking is deferred."
