# Data directories and release artifacts

## Runtime state

The package-aware `fable-mode serve` launcher selects state in this order:

1. `--state-dir PATH` when supplied;
2. `FABLE_DATA_DIR` when set;
3. Windows: `%LOCALAPPDATA%\FableMode\data`;
4. other systems: `~/.local/share/fable-mode/data`.

The direct legacy `fable-engine` entry point uses `FABLE_DATA_DIR` when set,
then Windows `%LOCALAPPDATA%\FableMode\data`, otherwise
`~/.local/share/fable-engine/data`. The two defaults intentionally differ.
Set `FABLE_DATA_DIR` explicitly when a host needs one known location.

V1 creates a `sessions/` directory below the selected data directory and
restricts it to the local user where the platform allows. CAS objects live
beside the selected data directory. State is not stored in the repository.
Session names are restricted to portable identifier characters and are used to
locate JSON files; do not put secrets in objectives, claims, evidence strings,
or payloads.

`FABLE_DATA_DIR` and `--state-dir` point to a real directory. The runtime
rejects unsafe path components such as symlinks/reparse points and special
files. These checks reduce accidental redirection; they are not a substitute
for OS account isolation or encrypted storage.

V2 run objects are in memory unless an integrating host provides persistence.
The broker operates on the explicitly supplied workspace and should use a
separate workspace from V1 state during evaluation.

## CAS behavior

Normal CAS reads verify the SHA-256 named by a `cas://` reference. A low-level
`verify=False` option exists for maintenance/diagnostics only and must not feed
model-visible or server-facing content. CAS is an addressing/integrity
mechanism, not encryption, access control, authenticity, or a guaranteed
compression or token-saving ratio. Limit access to the data directory as you
would any other local application state.

## Release archives

Release CI produces one archive per runner for Linux x86_64, macOS x86_64
(from the macOS 15 Intel runner), and Windows x86_64, plus a `SHA256SUMS` file.
Archive names use the bare package semver (for example, `1.2.0`) rather than
including the tag's leading `v`. The archives contain a frozen
`fable-mode` executable. They do not prove host compatibility or provide a
complete sandbox.

**Unsigned artifact warning:** release archives are currently unsigned. A
checksum detects accidental or in-transit changes only when the checksum file
was obtained from a trusted source; it does not authenticate the publisher.
Prefer a trusted release page and independently verify both the checksum and
provenance before execution. Do not treat a matching filename or checksum as a
signature.
