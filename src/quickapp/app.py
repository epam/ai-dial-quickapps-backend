import argparse

import uvicorn

if __name__ == "__main__":
    import os
    import sys
    from pathlib import Path

    import dotenv

    # Ensure the src directory is in the system path
    app_path = Path(__file__).parent.parent.absolute()
    sys.path.append(str(app_path))

    # Load environment variables from .env file
    dotenv_path = os.path.join(os.getcwd(), ".env")

    # noinspection PyBroadException
    try:
        dotenv.load_dotenv(dotenv_path)
    except Exception:
        pass

from quickapp.app_factory import AppFactory

app_factory = AppFactory()
app = app_factory.create()


def main():
    parser = argparse.ArgumentParser(description='Run the AI DIAL QuickApps2 Service with Uvicorn.')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Host to run the app on')
    parser.add_argument('--port', type=int, default=5000, help='Port to run the app on')
    parser.add_argument('--reload', action='store_true', help='Enable auto-reload')
    args = parser.parse_args()
    # log_config=None: logging is owned by LoggingConfig; uvicorn's default
    # dictConfig would re-sever uvicorn.* from root (and from OTLP export).
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload, log_config=None)


if __name__ == "__main__":
    main()
