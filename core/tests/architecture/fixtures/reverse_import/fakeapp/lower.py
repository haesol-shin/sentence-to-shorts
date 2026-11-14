"""Lower layer importing the upper layer breaks the layers contract."""

from fakeapp import upper


def lower() -> str:
    return f"lower:{upper.upper()}"
