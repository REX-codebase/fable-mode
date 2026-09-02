#!/usr/bin/env python3
"""Offline documentation, API-drift, and version consistency checks.

This checker intentionally does not fetch URLs or execute host integrations.
It is suitable for local runs and CI from the repository root.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
# Running ``python docs/check_docs.py`` puts docs/, not the checkout root, on
# sys.path. Add the repository explicitly for the source API import below.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MARKDOWN = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
V1_SCHEMA = ROOT / "fable_engine" / "fable_session.json"
CANONICAL_V1_COMMAND = "python -m unittest discover -s tests -p 'test_server*.py' -v"
SYSTEM3_FILES = {
    "fable_v2/system3/__init__.py", "fable_v2/system3/causal.py",
    "fable_v2/system3/dialectical.py", "fable_v2/system3/evolution.py",
    "fable_v2/system3/executive.py", "fable_v2/system3/free_energy.py",
    "fable_v2/system3/hyperbolic.py", "fable_v2/system3/induction.py",
    "fable_v2/system3/kripke.py", "fable_v2/system3/oracle.py",
}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def local_links(path: Path):
    # Covers normal Markdown links and images. Titles are deliberately not
    # interpreted; all links used by this repository have simple destinations.
    pattern = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+['\"][^)]*['\"])?\)")
    for match in pattern.finditer(path.read_text(encoding="utf-8")):
        yield match.group(1), path


def github_slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[`*_~]", "", value)
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    return re.sub(r"\s+", "-", value)


def headings(path: Path) -> set[str]:
    found: set[str] = set()
    fenced = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
            if match:
                found.add(github_slug(match.group(1)))
    return found


def check_links(errors: list[str]) -> None:
    for source in MARKDOWN:
        for destination, _ in local_links(source):
            if destination.startswith(("http://", "https://", "mailto:")):
                continue
            decoded = unquote(destination)
            target_text, _, fragment = decoded.partition("#")
            target = source.parent / target_text if target_text else source
            target = target.resolve()
            try:
                target.relative_to(ROOT.resolve())
            except ValueError:
                fail(errors, f"{source.relative_to(ROOT)}: link escapes repository: {destination}")
                continue
            if not target.is_file():
                fail(errors, f"{source.relative_to(ROOT)}: missing link target: {destination}")
                continue
            if fragment and target.suffix.lower() in {".md", ".markdown"}:
                if github_slug(fragment) not in headings(target):
                    fail(errors, f"{source.relative_to(ROOT)}: missing fragment #{fragment} in {target.relative_to(ROOT)}")


def package_versions(errors: list[str]) -> set[str]:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    setup = (ROOT / "setup.py").read_text(encoding="utf-8")
    init = (ROOT / "fable_mode" / "__init__.py").read_text(encoding="utf-8")
    py_match = re.search(r"^version\s*=\s*['\"]([^'\"]+)['\"]", pyproject, re.MULTILINE)
    setup_match = re.search(r"\bversion\s*=\s*['\"]([^'\"]+)['\"]", setup)
    init_match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", init)
    if not (py_match and setup_match and init_match):
        fail(errors, "could not read package versions from pyproject.toml/setup.py/fable_mode/__init__.py")
        return set()
    values = {py_match.group(1), setup_match.group(1), init_match.group(1)}
    if len(values) != 1:
        fail(errors, "package version mismatch between pyproject.toml, setup.py, and fable_mode.__version__")
    return values


def check_version_consistency(errors: list[str]) -> None:
    versions = package_versions(errors)
    if not versions:
        return
    version = next(iter(versions))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    marker = re.search(r"<!--\s*package-version:\s*([^\s]+)\s*-->", readme)
    if not marker:
        fail(errors, "README.md is missing <!-- package-version: ... --> marker")
    elif marker.group(1) != version:
        fail(errors, f"README package-version marker is {marker.group(1)}, package is {version}")

    server = (ROOT / "fable_engine" / "server.py").read_text(encoding="utf-8")
    server_versions = set(re.findall(r'"version"\s*:\s*"([^"]+)"', server))
    if version not in server_versions:
        fail(errors, f"fable_engine/server.py initialize/session version does not contain package version {version}")
    if any(item != version for item in server_versions):
        fail(errors, f"fable_engine/server.py contains versions other than package version: {sorted(server_versions)}")


def check_manifest_and_metadata(errors: list[str]) -> None:
    """Keep source, resource, wheel, and frozen package claims aligned."""
    try:
        from fable_mode.manifest import ALLOWED_FILES
        canonical = set(ALLOWED_FILES)
    except Exception as exc:
        fail(errors, f"cannot import canonical package manifest: {exc}")
        return
    try:
        resource = json.loads((ROOT / "fable_mode" / "resources.json").read_text(encoding="utf-8"))
        resource_files = resource.get("files") if isinstance(resource, dict) else None
        if set(resource_files or ()) != canonical or len(resource_files or ()) != len(canonical):
            fail(errors, "fable_mode/resources.json differs from manifest.ALLOWED_FILES")
    except (OSError, ValueError, TypeError) as exc:
        fail(errors, f"cannot load fable_mode/resources.json: {exc}")
    missing = sorted(rel for rel in canonical if not (ROOT / rel).is_file())
    if missing:
        fail(errors, f"canonical package manifest lists missing files: {missing}")
    system3 = {p.relative_to(ROOT).as_posix() for p in (ROOT / "fable_v2" / "system3").glob("*.py")}
    if system3 != SYSTEM3_FILES:
        fail(errors, "manifest/system3 package does not include every System 3 module")
    if not SYSTEM3_FILES <= canonical:
        fail(errors, "canonical package manifest omits part of fable_v2/system3")

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    setup = (ROOT / "setup.py").read_text(encoding="utf-8")
    py_description = re.search(r"^description\s*=\s*['\"]([^'\"]+)['\"]", pyproject, re.MULTILINE)
    setup_description = re.search(r"\bdescription\s*=\s*['\"]([^'\"]+)['\"]", setup)
    if not py_description or not setup_description or py_description.group(1) != setup_description.group(1):
        fail(errors, "package descriptions differ between pyproject.toml and setup.py")
    if "fable-v2-broker" not in pyproject or "fable-v2-broker" not in setup:
        fail(errors, "V2 broker entry point is missing from package metadata")
    project_section = pyproject.split("[project.scripts]", 1)[-1].split("\n[", 1)[0]
    project_scripts = set(re.findall(r"^\s{0,4}([a-z0-9-]+)\s*=\s*['\"]", project_section, re.MULTILINE))
    setup_section = setup.split('"console_scripts":', 1)[-1].split("],", 1)[0]
    setup_scripts = set(re.findall(r"^\s*['\"]([a-z0-9-]+)=", setup_section, re.MULTILINE))
    expected_scripts = {"fable-mode", "fable-engine", "fable-v1", "fable-v2-broker"}
    if project_scripts != expected_scripts or setup_scripts != expected_scripts:
        fail(errors, "console-script entry points differ between package metadata and the documented set")


def check_release_consistency(errors: list[str]) -> None:
    build = (ROOT / "build_scripts" / "build_release.py").read_text(encoding="utf-8")
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    policy = (ROOT / "docs" / "release-policy.md").read_text(encoding="utf-8")
    if "_tag_version(supplied)" not in build:
        fail(errors, "release archive naming does not normalize the leading tag v")
    if "macos-13" in release or "macos-15-intel" not in release:
        fail(errors, "release workflow uses a stale or undocumented macOS runner")
    for suffix in ("linux-x86_64.tar.gz", "macos-x86_64.zip", "windows-x86_64.zip"):
        if f"fable-mode-<version>-{suffix}" not in policy:
            fail(errors, f"release policy omits archive naming convention: {suffix}")


def check_documented_commands_and_outputs(errors: list[str]) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    troubleshooting = (ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
    if readme.count(CANONICAL_V1_COMMAND) != 1:
        fail(errors, "README does not contain exactly one canonical V1 test command")
    if CANONICAL_V1_COMMAND not in workflow:
        fail(errors, "test workflow does not run the canonical V1 test command")
    if CANONICAL_V1_COMMAND not in troubleshooting:
        fail(errors, "troubleshooting docs do not contain the canonical V1 test command")
    if "python fable_engine/test_server.py" in readme or "python fable_engine/test_server.py" in workflow:
        fail(errors, "stale direct V1 test command remains in README or CI")

    # Check documented output fields against the runtime-declared output schema,
    # rather than accepting prose that only mentions a successful transport.
    try:
        from fable_engine import server
        output = server.TOOL_SCHEMA.get("outputSchema", {})
        required = output.get("required", [])
        reference = (ROOT / "docs" / "mcp-reference.md").read_text(encoding="utf-8")
        if not isinstance(required, list) or not required:
            fail(errors, "runtime V1 output schema has no required fields")
        for field in required:
            if not isinstance(field, str) or f"`{field}`" not in reference:
                fail(errors, f"MCP reference omits runtime V1 output field: {field}")
    except Exception as exc:
        fail(errors, f"cannot inspect runtime output schema: {exc}")


def check_schema_and_api(errors: list[str]) -> None:
    try:
        schema = json.loads(V1_SCHEMA.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(errors, f"cannot load V1 schema: {exc}")
        return

    # Import in a temporary state directory so checking docs never writes to a
    # developer's normal Fable data directory.
    old_data = os.environ.get("FABLE_DATA_DIR")
    with tempfile.TemporaryDirectory(prefix="fable-doc-check-") as state:
        os.environ["FABLE_DATA_DIR"] = state
        try:
            from fable_engine import server
            runtime = server.TOOL_SCHEMA
        except Exception as exc:
            fail(errors, f"cannot import V1 TOOL_SCHEMA: {exc}")
            runtime = None
        finally:
            if old_data is None:
                os.environ.pop("FABLE_DATA_DIR", None)
            else:
                os.environ["FABLE_DATA_DIR"] = old_data

    if runtime is None:
        return
    disk_schema = schema.get("parameters", {})
    runtime_schema = runtime.get("inputSchema", {})
    disk_actions = list(disk_schema.get("properties", {}).get("action", {}).get("enum", []))
    runtime_actions = list(runtime_schema.get("properties", {}).get("action", {}).get("enum", []))
    if disk_actions != runtime_actions:
        fail(errors, "V1 schema action enum differs between fable_session.json and server.TOOL_SCHEMA")
    disk_properties = set(disk_schema.get("properties", {}))
    runtime_properties = set(runtime_schema.get("properties", {}))
    # ``accumulate_payload`` remains in the shipped descriptor for compatibility
    # with older host registrations, while the implementation reads ``payload``
    # for that action. Keep this explicit exception visible instead of hiding a
    # general schema drift.
    legacy_descriptor_only = {"accumulate_payload"}
    if (disk_properties - runtime_properties) - legacy_descriptor_only:
        fail(errors, "V1 schema has undocumented descriptor-only parameter properties")
    if runtime_properties - disk_properties:
        fail(errors, "V1 runtime TOOL_SCHEMA has parameter properties missing from fable_session.json")
    if disk_schema.get("required") != runtime_schema.get("required"):
        fail(errors, "V1 schema required fields differ between fable_session.json and server.TOOL_SCHEMA")

    # Property order and descriptions are presentation details, but types,
    # enums, nested object requirements, and union branches are API meaning.
    # Compare those semantics so a stale descriptor cannot pass merely because
    # its action list still happens to match.
    def schema_meaning(value: object) -> object:
        if isinstance(value, dict):
            keep = {key: value[key] for key in ("type", "enum", "required", "additionalProperties", "oneOf") if key in value}
            if "properties" in value and isinstance(value["properties"], dict):
                keep["properties"] = {name: schema_meaning(item) for name, item in value["properties"].items()}
            if "oneOf" in keep and isinstance(keep["oneOf"], list):
                keep["oneOf"] = [schema_meaning(item) for item in keep["oneOf"]]
            return keep
        if isinstance(value, list):
            return [schema_meaning(item) for item in value]
        return value

    for name in sorted(disk_properties & runtime_properties):
        if schema_meaning(disk_schema["properties"][name]) != schema_meaning(runtime_schema["properties"][name]):
            fail(errors, f"V1 schema property semantics differ for {name}")

    reference = (ROOT / "docs" / "mcp-reference.md").read_text(encoding="utf-8")
    for action in runtime_actions:
        if action not in reference:
            fail(errors, f"MCP reference does not mention V1 action: {action}")

    # Extract action comparisons from ExecutionBroker.handle without running a
    # broker or a child process. This catches additions/removals in docs.
    broker_path = ROOT / "fable_v2" / "execution_broker.py"
    try:
        tree = ast.parse(broker_path.read_text(encoding="utf-8"), filename=str(broker_path))
        broker_actions: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            if not (isinstance(node.left, ast.Name) and node.left.id == "action"):
                continue
            for comparator in node.comparators:
                values = comparator.elts if isinstance(comparator, (ast.Set, ast.Tuple, ast.List)) else [comparator]
                if isinstance(node.ops[0], (ast.In, ast.Eq)):
                    broker_actions.update(item.value for item in values if isinstance(item, ast.Constant) and isinstance(item.value, str))
        reference_broker = reference
        for action in ("probe", "probe_capabilities", "inspect_files", "execute_command", "write_file"):
            if action not in broker_actions:
                fail(errors, f"broker source no longer advertises expected action: {action}")
            if action not in reference_broker:
                fail(errors, f"MCP reference does not mention broker action: {action}")

        # Probe output is part of the host-facing contract. Exercise only the
        # side-effect-free probe with a temporary workspace and require the
        # reference to name every stable field a host can consume.
        from fable_v2.execution_broker import BROKER_PROBE_FIELDS, BrokerPolicy, ExecutionBroker
        with tempfile.TemporaryDirectory(prefix="fable-doc-broker-") as workspace:
            broker = ExecutionBroker(BrokerPolicy(Path(workspace), (Path(sys.executable).name,)))
            probe = broker.probe()
        stable_probe_fields = set(BROKER_PROBE_FIELDS)
        if set(probe) != stable_probe_fields:
            fail(errors, f"broker probe output fields changed unexpectedly: {sorted(probe)}")
        for field in stable_probe_fields:
            if f"`{field}`" not in reference_broker:
                fail(errors, f"MCP reference omits broker probe output field: {field}")
    except Exception as exc:
        fail(errors, f"cannot inspect broker API: {exc}")


# The package-level intelligent verifier surface is intentionally explicit.
# Keep this list in sync with fable_v2.__init__ and the architecture guide;
# adding a verifier class without documenting/exporting it is API drift.
INTELLIGENT_VERIFIER_API = frozenset({
    "Adjudication", "CalibrationMetrics", "Claim", "ClaimGraph",
    "CompositeVerifier", "Counterexample", "CounterexampleStore",
    "FunctionVerifier", "MetamorphicRelation", "MetamorphicVerifier",
    "MutationOperator", "MutationVerifier", "PlannedCheck", "PortfolioResult",
    "PropertyCheck", "PropertyVerifier", "RiskLevel", "ThreeValuedAdjudicator",
    "Verdict", "VerificationDecision", "Verifier", "VerifierDecision",
    "VerifierPlan", "VerifierPlanner", "VerifierPortfolio", "VerifierStatus",
})


def check_fable_v2_api(errors: list[str]) -> None:
    """Check exported verifier names and package export integrity."""
    try:
        import fable_v2
        import fable_v2.verifiers as verifiers
    except Exception as exc:
        fail(errors, f"cannot import fable_v2 public API: {exc}")
        return
    exported = getattr(fable_v2, "__all__", None)
    if not isinstance(exported, list) or not all(isinstance(name, str) for name in exported):
        fail(errors, "fable_v2.__all__ must be a list of string names")
        return
    if len(exported) != len(set(exported)):
        fail(errors, "fable_v2.__all__ contains duplicate names")
    missing_exports = sorted(name for name in exported if not hasattr(fable_v2, name))
    if missing_exports:
        fail(errors, f"fable_v2.__all__ contains missing attributes: {missing_exports}")
    exported_set = set(exported)
    missing_verifier_exports = sorted(INTELLIGENT_VERIFIER_API - exported_set)
    if missing_verifier_exports:
        fail(errors, f"intelligent verifier API is not exported by fable_v2: {missing_verifier_exports}")

    # Catch a newly declared public verifier type that was not added to the
    # checked API inventory. Imported typing helpers are excluded by module.
    declared = {
        name for name, value in vars(verifiers).items()
        if not name.startswith("_") and getattr(value, "__module__", None) == verifiers.__name__
    }
    undocumented = sorted(declared - INTELLIGENT_VERIFIER_API)
    if undocumented:
        fail(errors, f"new public verifier names require API inventory/documentation: {undocumented}")
    architecture = (ROOT / "docs" / "fable-v2-architecture.md").read_text(encoding="utf-8")
    for name in sorted(INTELLIGENT_VERIFIER_API):
        if f"`{name}`" not in architecture:
            fail(errors, f"architecture guide omits intelligent verifier API name: {name}")


def check_text_hygiene(errors: list[str]) -> None:
    # C0/C1 controls, replacement characters, and zero-width artifacts are not
    # valid in checked-in prose. Tabs/newlines/CR are allowed by Markdown.
    for path in MARKDOWN:
        text = path.read_text(encoding="utf-8")
        bad = [(index, hex(ord(char))) for index, char in enumerate(text)
               if (ord(char) < 32 and char not in "\t\n\r")
               or 0x7F <= ord(char) <= 0x9F
               or char in {"\ufffd", "\u200b", "\ufeff"}]
        if bad:
            fail(errors, f"{path.relative_to(ROOT)} contains control/corrupted characters: {bad[:5]}")

    # Keep claims in the landing page and Fable design docs qualified. These
    # terms previously appeared as absolute guarantees or ungrounded metrics.
    fable_docs = [ROOT / "README.md", *sorted((ROOT / "docs").glob("fable-*.md"))]
    forbidden = [
        (r"\bunbypassable\b", "unqualified unbypassable claim"),
        (r"\bACID\b", "unsupported ACID claim"),
        (r"\bWAL\b", "unsupported WAL claim"),
        (r"formal engineering proof", "unsupported formal engineering proof claim"),
        (r"\b\d+(?:\.\d+)?%", "unqualified effectiveness percentage"),
    ]
    for path in fable_docs:
        text = path.read_text(encoding="utf-8")
        for pattern, label in forbidden:
            if re.search(pattern, text, flags=re.IGNORECASE):
                fail(errors, f"{path.relative_to(ROOT)} contains {label}")


def main() -> int:
    errors: list[str] = []
    check_links(errors)
    check_version_consistency(errors)
    check_manifest_and_metadata(errors)
    check_release_consistency(errors)
    check_documented_commands_and_outputs(errors)
    check_schema_and_api(errors)
    check_fable_v2_api(errors)
    check_text_hygiene(errors)
    if errors:
        print("Documentation checks failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Documentation checks passed ({len(MARKDOWN)} Markdown files checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
