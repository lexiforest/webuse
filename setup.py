"""Compile the control plane into release artifacts, not editable installs."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist


ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / "src" / "webuse" / "_ui"


def validate_bundle():
    if not (BUNDLE / "server" / "index.mjs").is_file() or not (BUNDLE / "public").is_dir():
        raise RuntimeError(
            "The compiled UI is missing. Build releases from a source checkout "
            "with Node.js 24+ and npm."
        )
    native = [
        path for path in BUNDLE.rglob("*")
        if path.suffix in {".node", ".so", ".dylib", ".dll", ".exe"}
    ]
    if native:
        raise RuntimeError(f"The UI bundle must be platform independent: {native[0]}")


def build_ui():
    source = ROOT / "ui"
    if not (source / "package.json").is_file():
        # Published sdists already contain the build. Installing one needs no npm.
        validate_bundle()
        return
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        raise RuntimeError("Building a webuse release requires Node.js 24+ and npm on PATH.")
    version = subprocess.check_output([node, "--version"], text=True).strip()
    if int(version.lstrip("v").split(".")[0]) < 24:
        raise RuntimeError(f"Building the UI requires Node.js 24+; found {version}.")
    subprocess.run([npm, "ci"], cwd=source, check=True)
    subprocess.run(
        [npm, "run", "build"], cwd=source, check=True,
        env={**os.environ, "NITRO_PRESET": "node-server"},
    )
    output = source / ".output"
    # Copy only compiled runtime files, never source, node_modules from the
    # development tree, credentials, databases, or run data.
    with tempfile.TemporaryDirectory(prefix="webuse-ui-build-") as temporary:
        staged = Path(temporary)
        for name in ("server", "public"):
            shutil.copytree(output / name, staged / name)
        package = staged / "server" / "package.json"
        if package.is_file() and json.loads(package.read_text()).get("dependencies"):
            raise RuntimeError("The compiled UI has external dependencies; bundle them before releasing.")
        if any(staged.rglob("*.node")):
            raise RuntimeError("The compiled UI contains a platform-specific Node addon.")
        if BUNDLE.exists():
            shutil.rmtree(BUNDLE)
        shutil.copytree(staged, BUNDLE)
    validate_bundle()


class BuildPy(build_py):
    def run(self):
        if not self.editable_mode:
            build_ui()
            # A direct wheel rebuild must not keep obsolete hashed JS chunks.
            destination = Path(self.build_lib) / "webuse" / "_ui"
            if destination.exists():
                shutil.rmtree(destination)
        super().run()


class Sdist(sdist):
    def run(self):
        build_ui()
        super().run()


setup(cmdclass={"build_py": BuildPy, "sdist": Sdist})
