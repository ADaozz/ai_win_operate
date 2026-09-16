"""Application-specific exception hierarchy."""


class WindowsGuiAgentError(Exception):
    """Base class for application errors."""


class UnsupportedPlatformError(WindowsGuiAgentError):
    """Raised when a feature is unavailable on the current platform."""


class WindowNotFoundError(WindowsGuiAgentError):
    """Raised when a target HWND no longer identifies a window."""


class WindowOperationError(WindowsGuiAgentError):
    """Raised when Windows rejects a window operation."""


class WindowCaptureError(WindowsGuiAgentError):
    """Raised when a target window cannot be captured."""


class BlackWindowFrameError(WindowCaptureError):
    """Raised when Windows returns an unusable all-black target frame."""


class MinimizedWindowCaptureError(WindowCaptureError):
    """Raised when capture is requested for a minimized target window."""


class InputExecutionError(WindowsGuiAgentError):
    """Raised when a mouse or keyboard input cannot be safely executed."""


class ActionValidationError(WindowsGuiAgentError):
    """Raised when a structured action violates a safety constraint."""


class LLMClientError(WindowsGuiAgentError):
    """Base class for safe, user-facing LLM client failures."""


class MissingApiKeyError(LLMClientError):
    """Raised when DASHSCOPE_API_KEY is unavailable or empty."""


class LLMTimeoutError(LLMClientError):
    """Raised when the model endpoint exceeds the configured timeout."""


class LLMTransportError(LLMClientError):
    """Raised when the model endpoint cannot be reached."""


class LLMHTTPError(LLMClientError):
    """Raised when the model endpoint returns a non-success status."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Qwen returned HTTP {status_code}")


class LLMResponseStructureError(LLMClientError):
    """Raised when an HTTP response does not have the expected envelope."""


class EmptyModelResponseError(LLMClientError):
    """Raised when the model returns no structured content."""


class StructuredOutputError(LLMClientError):
    """Raised when structured content is not a valid AgentAction."""


class AgentRuntimeError(WindowsGuiAgentError):
    """Base class for Agent Runtime failures."""


class AgentStoppedError(AgentRuntimeError):
    """Raised when emergency stop blocks queued or in-progress work."""


class RepeatedActionError(AgentRuntimeError):
    """Raised when the model repeats the same action too many times."""


class EmergencyStopRegistrationError(WindowsGuiAgentError):
    """Raised when Windows cannot reserve the configured emergency hotkey."""
