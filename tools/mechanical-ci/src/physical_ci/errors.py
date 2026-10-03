class InputError(ValueError):
    """Invalid or unsupported input; never silently treated as a pass."""


class BackendError(RuntimeError):
    """A required backend is missing, incompatible, or failed."""
