#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3>=1.40,<2"]
# ///
"""LifeKernel's S3 upload, direct read and export entry point. Credentials stay outside Git."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
from urllib.parse import parse_qs, quote, unquote, urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def client(config_path: Path):
    config = json.loads(config_path.expanduser().read_text())
    credentials_path = Path(config["credentials_file"]).expanduser()
    credentials = dict(
        line.strip().split("=", 1)
        for line in credentials_path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    )
    if credentials_path.stat().st_mode & 0o077:
        raise ValueError("credentials_file must be readable only by its owner (chmod 600)")
    s3 = boto3.client(
        "s3", endpoint_url=config["endpoint"], region_name=config.get("region", "us-east-1"),
        aws_access_key_id=credentials["RUSTFS_ACCESS_KEY"],
        aws_secret_access_key=credentials["RUSTFS_SECRET_KEY"],
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3},
                      connect_timeout=5, read_timeout=60),
    )
    return s3, config["bucket"]


def key_path(value: str, bucket: str) -> tuple[str, str | None]:
    version = None
    if value.startswith("s3://"):
        uri = urlsplit(value)
        if uri.netloc != bucket:
            raise ValueError(f"URI bucket must be {bucket}")
        value = unquote(uri.path.lstrip("/"))
        version = parse_qs(uri.query).get("versionId", [None])[0]
    if not value or value.startswith("/") or ".." in PurePosixPath(value).parts:
        raise ValueError("key must be a nonempty relative object path without '..'")
    return value, version


def object_uri(bucket: str, key: str, version: str | None = None) -> str:
    uri = f"s3://{bucket}/{quote(key, safe='/')}"
    return uri + (f"?versionId={quote(version, safe='')}" if version else "")


def read(s3, bucket: str, key: str, output, version: str | None = None) -> dict:
    """Stream an object into the caller's output without creating a local copy."""
    response = s3.get_object(Bucket=bucket, Key=key, **({"VersionId": version} if version else {}))
    size = 0
    try:
        for chunk in response["Body"].iter_chunks(1024 * 1024):
            output.write(chunk)
            size += len(chunk)
        if size != response["ContentLength"]:
            raise IOError(f"incomplete read: {key}")
    finally:
        response["Body"].close()
    return {"key": key, "bytes": size, "version_id": response.get("VersionId")}


def stat(s3, bucket: str, key: str, version: str | None = None) -> dict:
    response = s3.head_object(Bucket=bucket, Key=key, **({"VersionId": version} if version else {}))
    return {"key": key, "bytes": response["ContentLength"], "version_id": response.get("VersionId")}


def put(s3, bucket: str, source: Path, key: str, immutable: bool = False) -> dict:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"not a regular file: {source}")
    if immutable:
        try:
            existing = s3.get_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in {"NoSuchKey", "404"}:
                raise
        else:
            try:
                with source.open("rb") as local:
                    while True:
                        chunk = local.read(1024 * 1024)
                        remote = existing["Body"].read(len(chunk) or 1)
                        if chunk != remote:
                            raise ValueError(f"immutable object differs: {key}")
                        if not chunk:
                            break
            finally:
                existing["Body"].close()
            version = existing.get("VersionId")
            uri = object_uri(bucket, key, version)
            return {"key": key, "version_id": version, "uri": uri, "unchanged": True}
    with source.open("rb") as stream:
        options = {"IfNoneMatch": "*"} if immutable else {}
        response = s3.put_object(Bucket=bucket, Key=key, Body=stream, **options)
    version = response.get("VersionId")
    uri = object_uri(bucket, key, version)
    return {"key": key, "version_id": version, "bytes": source.stat().st_size, "uri": uri}


def get(s3, bucket: str, key: str, destination: Path, version: str | None = None) -> dict:
    options = {"VersionId": version} if version else {}
    response = s3.get_object(Bucket=bucket, Key=key, **options)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".download-", delete=False) as stream:
            temporary = Path(stream.name)
            for chunk in response["Body"].iter_chunks(1024 * 1024):
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size != response["ContentLength"]:
            raise IOError(f"incomplete download: {key}")
        temporary.replace(destination)
    finally:
        response["Body"].close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"key": key, "path": str(destination), "bytes": response["ContentLength"],
            "version_id": response.get("VersionId")}


def objects(s3, bucket: str, prefix: str):
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        yield from page.get("Contents", [])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("~/.config/lifekernel/object-storage.json"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="create the configured bucket and enable versioning")
    upload = commands.add_parser("put")
    upload.add_argument("source", type=Path)
    upload.add_argument("key")
    upload.add_argument("--immutable", action="store_true")
    download = commands.add_parser("get")
    download.add_argument("key")
    download.add_argument("destination", type=Path)
    download.add_argument("--version-id")
    for name in ("read", "stat"):
        command = commands.add_parser(name, help="read an object to stdout" if name == "read" else "inspect an object")
        command.add_argument("key", **({"nargs": "+"} if name == "stat" else {}))
        command.add_argument("--version-id")
    tree = commands.add_parser("upload-tree")
    tree.add_argument("source", type=Path)
    tree.add_argument("prefix")
    tree.add_argument("--immutable", action="store_true")
    restore = commands.add_parser("restore")
    restore.add_argument("prefix")
    restore.add_argument("destination", type=Path)
    listing = commands.add_parser("list")
    listing.add_argument("prefix")
    args = parser.parse_args()
    s3, bucket = client(args.config)
    if args.command == "init":
        try:
            s3.head_bucket(Bucket=bucket)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in {"NoSuchBucket", "404"}:
                raise
            s3.create_bucket(Bucket=bucket)
        s3.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
        result = {"bucket": bucket, "versioning": s3.get_bucket_versioning(Bucket=bucket).get("Status")}
    elif args.command == "put":
        key, _ = key_path(args.key, bucket)
        result = put(s3, bucket, args.source, key, args.immutable)
    elif args.command == "get":
        key, version = key_path(args.key, bucket)
        result = get(s3, bucket, key, args.destination, args.version_id or version)
    elif args.command in {"read", "stat"}:
        if args.command == "read":
            key, version = key_path(args.key, bucket)
            read(s3, bucket, key, sys.stdout.buffer, args.version_id or version)
            return
        def inspect(value):
            key, version = key_path(value, bucket)
            return stat(s3, bucket, key, args.version_id or version)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(inspect, args.key))
        result = results[0] if len(results) == 1 else results
    else:
        prefix, _ = key_path(args.prefix, bucket)
        prefix = prefix.rstrip("/") + "/"
        if args.command == "upload-tree":
            if not args.source.is_dir() or args.source.is_symlink():
                raise ValueError("source must be a real directory")
            files = sorted(p for p in args.source.rglob("*") if p.is_file())
            if any(p.is_symlink() for p in args.source.rglob("*")):
                raise ValueError("upload-tree does not follow symlinks")
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda p: put(s3, bucket, p,
                    prefix + p.relative_to(args.source).as_posix(), args.immutable), files))
            result = {"prefix": prefix, "files": len(results),
                      "bytes": sum(p.stat().st_size for p in files),
                      "unchanged": sum(r.get("unchanged", False) for r in results)}
        elif args.command == "restore":
            root = args.destination.resolve()
            files = list(objects(s3, bucket, prefix))
            def recover(item):
                relative = item["Key"][len(prefix):]
                key_path(relative, bucket)
                dest = root / relative
                if not dest.resolve().is_relative_to(root):
                    raise ValueError("restore target escapes destination")
                return get(s3, bucket, item["Key"], dest)
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(recover, files))
            result = {"prefix": prefix, "files": len(results),
                      "bytes": sum(r["bytes"] for r in results), "destination": str(root)}
        else:
            files = list(objects(s3, bucket, prefix))
            result = {"prefix": prefix, "files": len(files), "bytes": sum(p["Size"] for p in files),
                      "objects": [{"key": p["Key"], "bytes": p["Size"]} for p in files]}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
