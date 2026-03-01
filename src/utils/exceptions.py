"""Application-wide exception hierarchy."""


class SimulationError(Exception):
    """Base for all simulation-related errors."""
    pass


class AvatarActionError(SimulationError):
    """Error during avatar action execution."""

    def __init__(self, avatar_id: str, action_name: str, message: str):
        self.avatar_id = avatar_id
        self.action_name = action_name
        super().__init__(f"Avatar {avatar_id} action '{action_name}' failed: {message}")


class ConfigurationError(Exception):
    """Configuration validation or loading error."""
    pass
