"""Start a project-local PostgreSQL for development without Docker.

Data lives in .pgdata/ inside the repository. Prints a SQLAlchemy URL and keeps running until
interrupted. Docker Compose remains the standard way to run the full stack.
"""

import argparse
import pathlib
import time

import pgserver

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="nifty_backtester")
    args = parser.parse_args()

    server = pgserver.get_server(ROOT / ".pgdata", cleanup_mode="stop")
    exists = server.psql(f"SELECT 1 FROM pg_database WHERE datname = '{args.database}'")
    if "1 row" not in exists:
        server.psql(f'CREATE DATABASE "{args.database}"')
    uri = server.get_uri(database=args.database)
    print(uri.replace("postgresql://", "postgresql+psycopg://"), flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.cleanup()


if __name__ == "__main__":
    main()
