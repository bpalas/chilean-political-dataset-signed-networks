#!/usr/bin/env python
"""Download Chilean Political Dataset from Hugging Face.

Usage:
    python scripts/download.py --what all
    python scripts/download.py --what raw
    python scripts/download.py --what processed

Requires HF_TOKEN in .env (read access to bpalacios/chilean-political-dataset).
Copy .env.example to .env and fill in your token.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

REPO_ID = "bpalacios/chilean-political-dataset"

# Patterns that map to each --what option
PATTERNS: dict[str, list[str]] = {
    "raw": ["raw/*"],
    "processed": ["processed/*"],
    "all": ["raw/*", "processed/*"],
}


def _token() -> str:
    """Read HF_TOKEN from environment or .env file."""
    token = os.environ.get("HF_TOKEN")
    if token:
        return token

    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("HF_TOKEN=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip()

    raise EnvironmentError(
        "HF_TOKEN not found. Copy .env.example to .env and fill in your token.\n"
        "Get a token at: https://huggingface.co/settings/tokens"
    )


def download_dataset(what: str = "all") -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        raise ImportError("Run: pip install huggingface_hub")

    token = _token()
    patterns = PATTERNS.get(what)
    if patterns is None:
        raise ValueError(f"Unknown --what value: {what!r}. Choose from: {list(PATTERNS)}")

    local_dir = Path(__file__).parent.parent / "data"
    local_dir.mkdir(exist_ok=True)

    print(f"[download] Descargando '{what}' desde {REPO_ID} ...")
    print(f"[download] Destino: {local_dir}")

    snapshot_download(
        repo_id=REPO_ID,
        repo_type="dataset",
        token=token,
        local_dir=str(local_dir),
        allow_patterns=patterns,
    )

    print(f"\n[done] Datos disponibles en {local_dir}")
    print("       Explora con: python scripts/stats.py")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Chilean Political Dataset from Hugging Face"
    )
    parser.add_argument(
        "--what",
        choices=list(PATTERNS),
        default="all",
        help="Qué descargar (default: all)",
    )
    args = parser.parse_args()
    download_dataset(what=args.what)


if __name__ == "__main__":
    main()
