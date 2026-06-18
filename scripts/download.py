#!/usr/bin/env python
"""Download Chilean Political Dataset from S3.

Usage:
    python scripts/download.py --what all
    python scripts/download.py --what raw
    python scripts/download.py --what processed
    python scripts/download.py --what gold
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path


def compute_sha256(filepath: str) -> str:
    """Compute SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def download_from_s3(bucket: str, key: str, local_path: str) -> None:
    """Download a file from S3 (stub for now)."""
    print(f"[download] Would download s3://{bucket}/{key} to {local_path}")
    print("           (Configure AWS credentials and uncomment boto3 call)")
    # import boto3
    # s3 = boto3.client('s3')
    # s3.download_file(bucket, key, local_path)


def download_dataset(what: str = "all", verify: bool = True) -> None:
    """Download dataset files."""
    base_dir = Path(__file__).parent.parent
    data_dir = base_dir / "data"

    data_dir.mkdir(exist_ok=True)

    # File manifest with S3 keys and checksums
    files = {
        "raw": {
            "s3_key": "articles_raw_v2.csv.gz",
            "local": data_dir / "raw" / "articles_raw_v2.csv.gz",
            "sha256": "abc123def456...",  # TODO: fill in actual checksums
            "size_gb": 1.2,
        },
        "processed": {
            "s3_key": "articles_v2.parquet",
            "local": data_dir / "processed" / "articles_v2.parquet",
            "sha256": "xyz789uvw...",
            "size_gb": 0.5,
        },
        "gold": {
            "s3_key": "gold_relations_v2.parquet",
            "local": data_dir / "gold" / "gold_relations_v2.parquet",
            "sha256": "ijk456...",
            "size_gb": 0.01,
        },
        "splits": {
            "s3_key": "splits.json",
            "local": data_dir / "gold" / "splits.json",
            "sha256": "lmn789...",
            "size_gb": 0.001,
        },
    }

    if what == "all":
        to_download = ["raw", "processed", "gold", "splits"]
    else:
        to_download = [what]

    bucket = "chilean-political-dataset"

    for key in to_download:
        if key not in files:
            print(f"[ERROR] Unknown file: {key}")
            continue

        file_info = files[key]
        local_path = file_info["local"]

        # Create directory if needed
        local_path.parent.mkdir(parents=True, exist_ok=True)

        # Check if already exists
        if local_path.exists():
            if verify:
                existing_hash = compute_sha256(str(local_path))
                if existing_hash == file_info["sha256"]:
                    print(f"[OK] {key}: already exists and hash matches")
                    continue
                else:
                    print(f"[WARNING] {key}: exists but hash mismatch. Re-downloading.")
            else:
                print(f"[SKIP] {key}: already exists (hash check disabled)")
                continue

        # Download
        print(f"[downloading] {key} ({file_info['size_gb']:.2f} GB)...")
        download_from_s3(bucket, file_info["s3_key"], str(local_path))

        # Verify if requested
        if verify:
            computed_hash = compute_sha256(str(local_path))
            if computed_hash == file_info["sha256"]:
                print(f"[OK] {key}: integrity verified")
            else:
                print(f"[ERROR] {key}: hash mismatch after download")
                print(f"       Expected: {file_info['sha256']}")
                print(f"       Got: {computed_hash}")

    print("\n[done] Download complete. Start exploring:")
    print(f"       python scripts/stats.py")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Chilean Political Dataset from S3"
    )
    parser.add_argument(
        "--what",
        choices=["all", "raw", "processed", "gold"],
        default="all",
        help="Which files to download",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        default=True,
        help="Verify checksums (default: True)",
    )
    parser.add_argument(
        "--no-verify",
        action="store_false",
        dest="verify",
        help="Skip checksum verification",
    )

    args = parser.parse_args()
    download_dataset(what=args.what, verify=args.verify)


if __name__ == "__main__":
    main()
