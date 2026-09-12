from app.workflows.agent import WorkflowAgent


class DataEvaluationAgent(WorkflowAgent):
    name = "data_evaluation"
    description = "Selects among complete measured candidates using the frozen evaluation protocol and deterministic tie rules; retains missing results and literature participation limits."
