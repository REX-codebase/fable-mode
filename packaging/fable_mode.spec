# Reproducible PyInstaller definition. Build with the pinned requirement in
# requirements-build.txt; release CI archives per-runner architecture.
from pathlib import Path

ROOT = Path(SPECPATH).parent

# Only reviewed runtime resources are bundled. Sessions, caches, media, .env,
# private archives, Manim, and development tests are intentionally absent.
datas = [
    (str(ROOT / "fable_mode" / "resources.json"), "fable_mode"),
    (str(ROOT / "fable_engine" / "fable_session.json"), "fable_engine"),
    (str(ROOT / "rules" / "AGENTS.md"), "rules"),
    (str(ROOT / "rules" / "GEMINI.md"), "rules"),
    (str(ROOT / "rules" / "fable-mode.md"), "rules"),
    (str(ROOT / "docs" / "fable-v1-v2-migration.md"), "docs"),
    (str(ROOT / "docs" / "fable-v2-architecture.md"), "docs"),
    (str(ROOT / "LICENSE"), "."),
]
hiddenimports = [
    "fable_engine.server",
    "fable_v2.adapters", "fable_v2.execution_broker", "fable_v2.protocol",
    "fable_v2.runtime", "fable_v2.verifiers",
    "fable_v2.system3",
    "fable_v2.system3.causal", "fable_v2.system3.dialectical",
    "fable_v2.system3.evolution", "fable_v2.system3.executive",
    "fable_v2.system3.free_energy", "fable_v2.system3.hyperbolic",
    "fable_v2.system3.induction", "fable_v2.system3.kripke",
    "fable_v2.system3.oracle",
]

analysis = Analysis(
    [str(ROOT / "fable_mode_entry.py")],
    pathex=[str(ROOT)],
    binaries=[], datas=datas, hiddenimports=hiddenimports,
    excludes=["fable_engine.test_server", "tests", "manim", "tkinter"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, analysis.binaries, analysis.datas,
    name="fable-mode", console=True, debug=False, strip=False, upx=False,
)
