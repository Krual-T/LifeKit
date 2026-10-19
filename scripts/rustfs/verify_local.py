#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3>=1.40,<2"]
# ///
"""Verify S3 object operations, optionally restarting the matching local RustFS service."""

import argparse
import importlib.util
from ipaddress import ip_address
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from uuid import uuid4


SERVICE = "lifekernel-rustfs.service"
DEFAULT_CONFIG = Path("~/.config/lifekernel/object-storage.json")


def local_service_environment(config_path: Path) -> dict:
    """Match the selected endpoint to this user's installed single RustFS instance."""
    config = json.loads(config_path.expanduser().read_text())
    endpoint = urlsplit(config["endpoint"])
    try:
        loopback = endpoint.hostname == "localhost" or ip_address(endpoint.hostname).is_loopback
    except ValueError:
        loopback = False
    if not loopback or endpoint.scheme != "http" or endpoint.path not in {"", "/"}:
        raise ValueError("service restart requires this machine's HTTP loopback RustFS endpoint")
    credentials = Path.home() / ".config/lifekernel/rustfs.env"
    if Path(config["credentials_file"]).expanduser().resolve() != credentials.resolve():
        raise ValueError("selected configuration does not use this local RustFS instance's credentials")
    parameters = dict(
        line.strip().split("=", 1) for line in credentials.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    )
    listener = urlsplit("http://" + parameters.get("RUSTFS_ADDRESS", ""))
    if ((endpoint.port or 80) != listener.port
            or listener.hostname not in {endpoint.hostname, "0.0.0.0", "::"}):
        raise ValueError("selected endpoint does not match the local RustFS listener")
    env = dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}",
               DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{os.getuid()}/bus")
    result = subprocess.run(
        ["systemctl", "--user", "show", SERVICE, "--property=FragmentPath",
         "--property=EnvironmentFiles", "--property=ActiveState"],
        env=env, check=True, capture_output=True, text=True,
    )
    properties = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    expected_unit = Path.home() / ".config/systemd/user" / SERVICE
    environment_files = re.findall(r"(.+?) \(ignore_errors=(?:yes|no)\)(?: |$)",
                                   properties.get("EnvironmentFiles", ""))
    if (Path(properties.get("FragmentPath", "")).resolve() != expected_unit.resolve()
            or str(credentials) not in environment_files or properties.get("ActiveState") != "active"):
        raise ValueError("the active local RustFS service does not match the selected configuration")
    return env


def load_storage():
    spec = importlib.util.spec_from_file_location("object_store", Path(__file__).parents[1] / "object_store.py")
    storage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(storage)
    return storage


def verify(config: Path, *, restart_local_service: bool = False) -> dict:
    env = local_service_environment(config) if restart_local_service else None
    storage = load_storage()
    s3, bucket = storage.client(config)
    prefix = "validation/" + uuid4().hex + "/"
    versions, checks = [], []
    try:
        with tempfile.TemporaryDirectory(prefix="lifekernel-storage-check-") as directory:
            root = Path(directory)
            source, dest = root / "source.txt", root / "restored.txt"
            source.write_text("original evidence\n")
            first = storage.put(s3, bucket, source, prefix + "version.txt")
            versions.append(first)
            assert first["version_id"], "server did not assign a version"
            source.write_text("new observation\n")
            second = storage.put(s3, bucket, source, prefix + "version.txt")
            versions.append(second)
            assert first["version_id"] != second["version_id"]
            storage.get(s3, bucket, prefix + "version.txt", dest, first["version_id"])
            assert dest.read_text() == "original evidence\n"
            checks.append("overwrite retains original version")
            fixed = storage.put(s3, bucket, source, prefix + "immutable.txt", immutable=True)
            versions.append(fixed)
            assert storage.put(s3, bucket, source, prefix + "immutable.txt", immutable=True)["unchanged"]
            source.write_text("changed evidence\n")
            try:
                storage.put(s3, bucket, source, prefix + "immutable.txt", immutable=True)
            except ValueError:
                pass
            else:
                raise AssertionError("immutable evidence was overwritten")
            checks.append("immutable evidence rejects changed contents")
            try:
                storage.get(s3, bucket, prefix + "missing", dest)
            except storage.ClientError:
                pass
            else:
                raise AssertionError("missing object unexpectedly exists")
            assert dest.read_text() == "original evidence\n"
            checks.append("failed download preserves existing file")
            if restart_local_service:
                subprocess.run(["systemctl", "--user", "restart", SERVICE], env=env, check=True)
                for attempt in range(20):
                    try:
                        storage.get(s3, bucket, prefix + "version.txt", dest, first["version_id"])
                        break
                    except Exception:
                        if attempt == 19:
                            raise
                        time.sleep(1)
                assert dest.read_text() == "original evidence\n"
                storage.get(s3, bucket, prefix + "version.txt", dest)
                assert dest.read_text() == "new observation\n"
                checks.append("restart preserves current and historical object versions")
            return {"ok": True, "checks": checks, "service_restarted": restart_local_service}
    finally:
        # Only this invocation's known validation versions; no user data is removed.
        for obj in versions:
            s3.delete_object(Bucket=bucket, Key=obj["key"], VersionId=obj["version_id"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--restart-local-service", action="store_true",
                        help="also restart the matching local user service; run only when it is idle")
    args = parser.parse_args(argv)
    print(json.dumps(verify(args.config, restart_local_service=args.restart_local_service), ensure_ascii=False))


if __name__ == "__main__":
    main()
