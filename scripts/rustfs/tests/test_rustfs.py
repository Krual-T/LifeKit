import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


setup = load("setup_local")
verify = load("verify_local")


class FakeStorage:
    class ClientError(Exception):
        pass

    def __init__(self):
        self.objects, self.deleted, self.configs = {}, [], []

    def client(self, config):
        self.configs.append(config)
        return self, "test-bucket"

    def put(self, client, bucket, source, key, immutable=False):
        data = source.read_bytes()
        versions = self.objects.setdefault(key, {})
        if immutable and versions:
            version = next(reversed(versions))
            if versions[version] != data:
                raise ValueError("immutable content differs")
            return {"key": key, "version_id": version, "unchanged": True}
        version = str(len(versions) + 1)
        versions[version] = data
        return {"key": key, "version_id": version}

    def get(self, client, bucket, key, destination, version=None):
        if key not in self.objects:
            raise self.ClientError("NoSuchKey")
        versions = self.objects[key]
        destination.write_bytes(versions[version or next(reversed(versions))])

    def delete_object(self, **kwargs):
        self.deleted.append(kwargs)
        del self.objects[kwargs["Key"]][kwargs["VersionId"]]


class RustFSTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lifekernel-rustfs-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.addCleanup(patch.stopall)
        patch.object(Path, "home", return_value=self.home).start()
        self.config = self.home / "selected-config.json"
        self.credentials = self.home / ".config/lifekernel/rustfs.env"
        self.unit = self.home / ".config/systemd/user/lifekernel-rustfs.service"

    def local_config(self, **changes):
        self.credentials.parent.mkdir(parents=True, exist_ok=True)
        self.credentials.write_text("RUSTFS_ADDRESS=127.0.0.1:9000\n")
        config = {"endpoint": "http://127.0.0.1:9000", "bucket": "test-bucket",
                  "credentials_file": str(self.credentials), **changes}
        self.config.write_text(json.dumps(config))
        return config

    def service_result(self, **changes):
        properties = {"FragmentPath": str(self.unit), "ActiveState": "active",
                      "EnvironmentFiles": f"{self.credentials} (ignore_errors=no)", **changes}
        return subprocess.CompletedProcess([], 0, "\n".join(f"{k}={v}" for k, v in properties.items()))

    def test_install_is_private_and_preserves_existing_configuration(self):
        archive = self.home / "rustfs.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("rustfs", b"test executable, never run")
        with patch("sys.argv", ["setup_local.py", str(archive)]), contextlib.redirect_stdout(io.StringIO()):
            setup.main()
        config_path = self.home / ".config/lifekernel/object-storage.json"
        config = json.loads(config_path.read_text())
        self.assertEqual(config["credentials_file"], str(self.credentials))
        self.assertEqual(config["endpoint"], "http://127.0.0.1:9000")
        self.assertEqual(self.credentials.stat().st_mode & 0o777, 0o600)
        self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.unit.read_bytes(), (ROOT / "lifekernel-rustfs.service").read_bytes())
        config["bucket"] = "existing-bucket"
        config_path.write_text(json.dumps(config))
        credentials = self.credentials.read_bytes()
        with patch("sys.argv", ["setup_local.py", str(archive)]), contextlib.redirect_stdout(io.StringIO()):
            setup.main()
        self.assertEqual(json.loads(config_path.read_text())["bucket"], "existing-bucket")
        self.assertEqual(self.credentials.read_bytes(), credentials)
        self.unit.write_text("existing custom service\n")
        with patch("sys.argv", ["setup_local.py", str(archive)]), self.assertRaises(SystemExit):
            setup.main()
        self.assertEqual(self.unit.read_text(), "existing custom service\n")

    def test_default_verification_uses_selected_config_without_systemctl(self):
        storage = FakeStorage()
        with patch.object(verify, "load_storage", return_value=storage), patch.object(verify.subprocess, "run") as run:
            result = verify.verify(self.config)
        self.assertEqual(storage.configs, [self.config])
        run.assert_not_called()
        self.assertFalse(result["service_restarted"])
        self.assertEqual(len(result["checks"]), 3)
        self.assertEqual(len(storage.deleted), 3)
        self.assertTrue(all(obj["Key"].startswith("validation/") for obj in storage.deleted))
        self.assertTrue(all(not versions for versions in storage.objects.values()))

    def test_restart_rejects_external_endpoint_before_any_service_or_s3_call(self):
        self.local_config(endpoint="https://objects.example.com")
        with patch.object(verify, "load_storage") as load_storage, patch.object(verify.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                verify.verify(self.config, restart_local_service=True)
        load_storage.assert_not_called()
        run.assert_not_called()

    def test_restart_rejects_other_credentials_or_listener(self):
        for changes in ({"credentials_file": str(self.home / "other.env")},
                        {"endpoint": "http://127.0.0.1:9100"}):
            with self.subTest(changes=changes):
                self.local_config(**changes)
                with patch.object(verify.subprocess, "run") as run, self.assertRaises(ValueError):
                    verify.local_service_environment(self.config)
                run.assert_not_called()
        self.local_config()
        self.credentials.write_text("RUSTFS_ADDRESS=192.0.2.1:9000\n")
        with patch.object(verify.subprocess, "run") as run, self.assertRaises(ValueError):
            verify.local_service_environment(self.config)
        run.assert_not_called()

    def test_restart_rejects_a_different_or_inactive_service(self):
        self.local_config()
        for changes in ({"FragmentPath": str(self.home / "another.service")},
                        {"EnvironmentFiles": "/tmp/another.env (ignore_errors=no)"},
                        {"ActiveState": "inactive"}):
            with self.subTest(changes=changes), patch.object(verify, "load_storage") as load_storage:
                with patch.object(verify.subprocess, "run", return_value=self.service_result(**changes)) as run:
                    with self.assertRaises(ValueError):
                        verify.verify(self.config, restart_local_service=True)
                self.assertEqual(run.call_count, 1)
                self.assertIn("show", run.call_args.args[0])
                load_storage.assert_not_called()

    def test_explicit_matching_service_restarts_once_and_checks_persistence(self):
        self.local_config()
        storage = FakeStorage()
        with patch.object(verify, "load_storage", return_value=storage):
            with patch.object(verify.subprocess, "run", return_value=self.service_result()) as run:
                result = verify.verify(self.config, restart_local_service=True)
        self.assertTrue(result["service_restarted"])
        self.assertEqual(len(result["checks"]), 4)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[-1].args[0], ["systemctl", "--user", "restart", verify.SERVICE])
        self.assertEqual(len(storage.deleted), 3)

    def test_cli_passes_selected_config_and_explicit_restart(self):
        with patch.object(verify, "verify", return_value={"ok": True}) as check:
            with contextlib.redirect_stdout(io.StringIO()):
                verify.main(["--config", str(self.config), "--restart-local-service"])
        check.assert_called_once_with(self.config, restart_local_service=True)


if __name__ == "__main__":
    unittest.main()
