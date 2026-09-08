from app.workflows.agent import WorkflowAgent


class DataDeliveryAgent(WorkflowAgent):
    name = "data_delivery"
    description = "Packages verified labeled EEG arrays, subject-wise splits and provenance for training."
