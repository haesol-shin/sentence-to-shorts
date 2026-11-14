"""Run the local server: python -m app"""

from __future__ import annotations

import uvicorn

from app.bootstrap import declare
from app.main import create_app


def main() -> None:
    declaration = declare()
    settings = declaration.settings
    uvicorn.run(
        create_app(declaration=declaration),
        host=settings.bind_host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
