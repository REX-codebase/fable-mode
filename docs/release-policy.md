# Release and versioning policy

## Version source of truth

The package uses one version in three checked-in locations:

- `[project].version` in `pyproject.toml`;
- `version` in `setup.py`; and
- `fable_mode.__version__` in `fable_mode/__init__.py`.

The V1 server's initialize response must report the same version. The package
aware README marker and the documentation checker are deliberately kept in sync
with these values. `build_scripts/build_release.py` also validates package
versions before building.

Use semantic versioning for released package versions (`MAJOR.MINOR.PATCH`):

- patch: compatible fixes, documentation, and security maintenance;
- minor: backward-compatible features or new experimental surfaces;
- major: intentional incompatible API or protocol changes.

A V1 MCP action or schema change must be called out in release notes. V2 is
experimental and may change before it has a compatibility promise; migration
docs must describe any changed contract or entry point.

## Tags and archives

Release CI runs for tags matching `v*.*.*`. The tag without the leading `v`
must equal the package version. Build runners currently publish:

- `fable-mode-<version>-linux-x86_64.tar.gz`;
- `fable-mode-<version>-macos-x86_64.zip` (built on the macOS 15 Intel runner);
  and
- `fable-mode-<version>-windows-x86_64.zip`;

plus `SHA256SUMS`. `<version>` is the bare package semver (for example,
`1.2.0`), not the tag spelling `v1.2.0`; check the release assets rather than
guessing a filename.

Artifacts are currently **unsigned**. Checksums help detect changes but do not
authenticate the publisher. Obtain release metadata from a trusted channel,
verify the archive checksum, and review provenance before running an archive.
Do not describe a checksum as a signature.

## Before publishing

1. Update all three package version locations.
2. Update the README package-version marker and version-sensitive examples.
3. Update the source-of-truth map if files or commands changed.
4. Run `python docs/check_docs.py`.
5. Run the V1 suite and the complete `tests/` suite.
6. Build and smoke-test each available artifact on its target runner.
7. Record compatibility and known limitations in the release notes.

No release should imply model effectiveness or security properties that were
not measured for that release and deployment.
