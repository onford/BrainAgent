class BrainAgentError(Exception):
    """Base application exception."""


class AgentNotFoundError(BrainAgentError):
    pass


class ToolNotFoundError(BrainAgentError):
    pass


class CredentialConfigurationError(BrainAgentError):
    pass


class CredentialValidationError(BrainAgentError):
    pass


class ToolNotConfiguredError(BrainAgentError):
    pass


class ToolDisabledError(BrainAgentError):
    pass


class ToolCredentialInvalidError(BrainAgentError):
    pass


class ExternalToolRateLimitError(BrainAgentError):
    pass


class ExternalToolUnavailableError(BrainAgentError):
    pass


class LLMConfigurationError(BrainAgentError):
    pass
