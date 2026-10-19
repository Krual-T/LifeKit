#!/usr/bin/env python3
"""Install the downloaded official 1.0.3 binary and private per-user service files."""

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import zipfile


def private_create(path, text):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    user = Path.home()
    binary = user / ".local/opt/rustfs/1.0.3/rustfs"
    config = user / ".config/lifekernel"
    data = user / ".local/share/lifekernel/rustfs"
    unit = user / ".config/systemd/user/lifekernel-rustfs.service"
    for directory in (binary.parent, config, data, data / "volumes", data / "logs", unit.parent):
        directory.mkdir(parents=True, exist_ok=True)
    data.chmod(0o700)
    if not binary.exists():
        with zipfile.ZipFile(args.archive) as archive, archive.open("rustfs") as source:
            with binary.open("xb") as target:
                shutil.copyfileobj(source, target)
        binary.chmod(0o755)
    credentials = config / "rustfs.env"
    if not credentials.exists():
        private_create(credentials, "\n".join([
            f"RUSTFS_ACCESS_KEY={secrets.token_hex(12)}",
            f"RUSTFS_SECRET_KEY={secrets.token_urlsafe(36)}",
            f"RUSTFS_VOLUMES={data / 'volumes'}",
            "RUSTFS_ADDRESS=127.0.0.1:9000",
            "RUSTFS_CONSOLE_ENABLE=true",
            "RUSTFS_CONSOLE_ADDRESS=127.0.0.1:9001",
            "RUSTFS_OBS_LOGGER_LEVEL=warn",
            f"RUSTFS_OBS_LOG_DIRECTORY={data / 'logs'}",
            "",
        ]))
    client_config = config / "object-storage.json"
    if not client_config.exists():
        private_create(client_config, json.dumps({
            "endpoint": "http://127.0.0.1:9000", "region": "us-east-1", "bucket": "lifekernel",
            "credentials_file": str(credentials),
        }, indent=2) + "\n")
    source_unit = Path(__file__).with_name("lifekernel-rustfs.service")
    if unit.exists() and unit.read_bytes() != source_unit.read_bytes():
        raise SystemExit(f"Existing service differs; inspect before replacing: {unit}")
    shutil.copyfile(source_unit, unit)
    print(json.dumps({"binary": str(binary), "data": str(data), "unit": str(unit),
                      "config": str(client_config), "credentials": str(credentials)}))


if __name__ == "__main__":
    main()
