"""Register a strategy version with its Pine source, through the running API.

Example, from the repository root:

    python scripts/register_strategy.py --pine prompt/strategy.pine --version 1.0.0
"""

import argparse
from pathlib import Path

import httpx

from app.strategy.parameters import STRATEGY_NAME


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pine", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--description", default="Initial port of the Pine script")
    parser.add_argument("--api", default="http://localhost:8000/api/v1")
    args = parser.parse_args()

    with httpx.Client(base_url=args.api, timeout=30) as client:
        strategies = client.get("/strategies").raise_for_status().json()
        strategy = next((s for s in strategies if s["name"] == STRATEGY_NAME), None)
        if strategy is None:
            strategy = (
                client.post("/strategies", json={"name": STRATEGY_NAME}).raise_for_status().json()
            )
        response = client.post(
            f"/strategies/{strategy['id']}/versions",
            json={
                "version": args.version,
                "pine_source": args.pine.read_text(encoding="utf-8"),
                "pine_source_reference": args.pine.name,
                "change_description": args.description,
            },
        )
        response.raise_for_status()
        version = response.json()
        print(f"Registered {STRATEGY_NAME} {version['version']}")
        print(f"Code hash: {version['code_hash']}")


if __name__ == "__main__":
    main()
