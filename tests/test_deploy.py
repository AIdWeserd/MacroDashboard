"""Exercise the deployment state machine with a fake Docker CLI, without a VM."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which("bash") and os.name == "posix", "Linux deployment script")
class DeployTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "macro"
        self.root.mkdir()
        (self.root / ".env").touch()
        (self.root / "compose.env").touch()
        self.old = self.root / "releases" / ("a" * 40 + "-1-1")
        self.new = self.root / "releases" / ("b" * 40 + "-2-1")
        self.image = "ghcr.io/example/macro@sha256:" + "c" * 64
        for release in (self.old, self.new):
            release.mkdir(parents=True)
            (release / "compose.yaml").write_text("services: {}\n")
            (release / "image").write_text(self.image + "\n")
        source = Path("scripts/deploy.sh").read_text()
        self.script = self.root / "deploy.sh"
        self.script.write_text(source.replace("/opt/macrodashboard", str(self.root)))
        binary = self.root / "bin"
        binary.mkdir()
        docker = binary / "docker"
        docker.write_text('''#!/bin/bash
set -eu
echo "$*" >> "$TEST_ROOT/commands"
if [[ -f "$TEST_ROOT/fail" ]] && [[ " $* " == *" $(cat "$TEST_ROOT/fail") "* ]]; then
  rm "$TEST_ROOT/fail"
  exit 42
fi
''')
        docker.chmod(0o755)
        self.env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ["PATH"], TEST_ROOT=str(self.root))

    def deploy(self):
        return subprocess.run(
            ["bash", str(self.script), str(self.new), self.image],
            env=self.env, text=True, capture_output=True, timeout=15,
        )

    def previous(self):
        (self.root / "current").symlink_to(self.old)

    def commands(self):
        return (self.root / "commands").read_text()

    def test_first_deployment_sets_current_after_checks(self):
        result = self.deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "current").resolve(), self.new)
        self.assertIn("scripts.check_app", self.commands())
        self.assertNotIn("scripts.backup", self.commands())

    def test_upgrade_backs_up_and_records_previous(self):
        self.previous()
        result = self.deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "current").resolve(), self.new)
        self.assertEqual((self.root / "previous").resolve(), self.old)
        commands = self.commands()
        self.assertLess(commands.index("stop updater"), commands.index("scripts.backup"))
        self.assertLess(commands.index("scripts.backup"), commands.index("up -d"))

    def test_pull_failure_leaves_old_release_running(self):
        self.previous()
        (self.root / "fail").write_text("pull")
        self.assertNotEqual(self.deploy().returncode, 0)
        self.assertEqual((self.root / "current").resolve(), self.old)
        self.assertNotIn("stop updater", self.commands())

    def test_failed_render_restores_old_containers(self):
        self.previous()
        (self.root / "fail").write_text("scripts.check_app")
        result = self.deploy()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / "current").resolve(), self.old)
        self.assertIn(str(self.old / "compose.yaml") + " up -d", self.commands())

    def test_first_deployment_failure_stops_failed_stack(self):
        (self.root / "fail").write_text("up")
        self.assertNotEqual(self.deploy().returncode, 0)
        self.assertFalse((self.root / "current").exists())
        self.assertIn(" down", self.commands())


if __name__ == "__main__":
    unittest.main()
