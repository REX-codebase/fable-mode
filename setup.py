import shutil
from pathlib import Path

from setuptools import setup, find_packages
from setuptools.command.build_py import build_py as _build_py

README = (Path(__file__).parent / "README.md").read_text(encoding="utf-8")

_SKILL_SOURCE = Path(__file__).resolve().parent / "skills" / "fable-mode"


class build_py(_build_py):
    """Bundle the canonical Agent Skill tree into the wheel as package data.

    ``pip`` and ``uvx`` install the wheel, so the explicit
    ``fable-mode install-skill`` flow can only work for those users when the
    skill tree travels inside the ``fable_mode`` package, not just in the
    sdist.  The checkout tree stays the single source of truth; it is copied
    into the build here.
    """

    def run(self):
        super().run()
        if getattr(self, "editable_mode", False):
            # Editable installs resolve the skill tree from the source
            # checkout, so no staged copy is needed.
            return
        copied = 0
        destination_root = Path(self.build_lib) / "fable_mode" / "skills" / "fable-mode"
        for source in sorted(_SKILL_SOURCE.rglob("*")):
            if not source.is_file():
                continue
            destination = destination_root / source.relative_to(_SKILL_SOURCE)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            copied += 1
        if copied == 0:
            raise RuntimeError("canonical skill tree is missing from the source tree")


setup(
    name="fable-engine",
    version="1.3.7",
    description="Independent deterministic System 2 cognitive engine and mechanical time-lock MCP server",
    long_description=README,
    long_description_content_type="text/markdown",
    license="MIT",
    packages=find_packages(),
    py_modules=["fable_mode_entry", "fable_compressor"],
    package_data={"fable_mode": ["resources.json", "LICENSE"], "fable_engine": ["fable_session.json"]},
    python_requires=">=3.10",
    install_requires=[],
    cmdclass={"build_py": build_py},
    entry_points={
        "console_scripts": [
            # Portable package-aware installer/runtime.
            "fable-mode=fable_mode.launcher:main",
            # Legacy V1 MCP entry point.
            "fable-engine=fable_engine.server:main",
            "fable-v1=fable_engine.server:main",
            # V2 process execution boundary.
            "fable-v2-broker=fable_v2.execution_broker:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
