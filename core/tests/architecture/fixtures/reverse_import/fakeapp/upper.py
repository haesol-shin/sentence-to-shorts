"""Upper layer importing the lower layer is allowed; lower returning the favour is not."""

from fakeapp import lower


def upper() -> str:
    return f"upper:{lower.lower()}"
