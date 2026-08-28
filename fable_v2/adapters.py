"""Thin host adapters for portable Fable V2 integrations.

The profiles describe a contract, not a claim that every host currently
supports every capability.  An adapter should probe the host at startup and
only advertise capabilities it can actually provide.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping


@dataclass(frozen=True)
class HostCapabilities:
    host: str
    capabilities: frozenset[str] = frozenset()
    tool_aliases: Mapping[str, str] = field(default_factory=dict)

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def normalize(self, tool_name: str) -> str:
        return self.tool_aliases.get(tool_name, tool_name)

    def compatibility_report(self, required: Iterable[str]) -> dict[str, object]:
        required_set = set(required)
        available = required_set & self.capabilities
        missing = required_set - self.capabilities
        return {
            "host": self.host,
            "compatible": not missing,
            "required": sorted(required_set),
            "available": sorted(available),
            "missing": sorted(missing),
        }


# These are conservative baseline profiles.  Real adapters should replace
# them after probing the host, rather than assuming a feature is available.
HOST_PROFILES: dict[str, HostCapabilities] = {
    "antigravity": HostCapabilities(
        "antigravity",
        frozenset({"inspect_files", "search_web", "execute_command", "edit_files",
                   "run_tests", "delegate_agents"}),
        {"run_command": "execute_command", "write_to_file": "edit_files"},
    ),
    "claude-code": HostCapabilities(
        "claude-code",
        frozenset({"inspect_files", "execute_command", "edit_files", "run_tests"}),
        {"shell": "execute_command"},
    ),
    "codex": HostCapabilities(
        "codex",
        frozenset({"inspect_files", "execute_command", "edit_files", "run_tests"}),
        {"shell": "execute_command"},
    ),
    "cursor": HostCapabilities(
        "cursor",
        frozenset({"inspect_files", "execute_command", "edit_files", "run_tests"}),
        {"terminal": "execute_command"},
    ),
    "grok-build": HostCapabilities("grok-build"),
    "zapia": HostCapabilities(
        "zapia",
        frozenset({"inspect_files", "search_web", "execute_command", "run_tests",
                   "delegate_agents"}),
    ),
}


def get_profile(host: str) -> HostCapabilities:
    """Return a conservative profile; unknown hosts start with no claims."""
    key = host.strip().lower()
    if not key:
        raise ValueError("host must be a non-empty string")
    return HOST_PROFILES.get(key, HostCapabilities(key))
