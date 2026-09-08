from app.workflows.agent import WorkflowAgent


class DataCollectionAgent(WorkflowAgent):
    name = "data_collection"
    description = "Converts inspected source EEG to standardized BIDS and records basic screening."
