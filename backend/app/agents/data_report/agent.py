from app.workflows.agent import WorkflowAgent


class DataReportAgent(WorkflowAgent):
    name = "data_report"
    description = "Renders a dataset, preprocessing and training-data report from actual workflow outputs."
