class BrainAgentError(Exception):
    """Base application exception."""


class AgentNotFoundError(BrainAgentError):
    pass


class ToolNotFoundError(BrainAgentError):
    pass


class LLMConfigurationError(BrainAgentError):
    pass
