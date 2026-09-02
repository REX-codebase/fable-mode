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
    """Expected capabilities plus optional runtime-probed capabilities.

    A profile is never authoritative until ``attest`` is called with the
    result of a real host probe. This prevents documentation defaults from
    silently becoming permission or compatibility claims.
    """

    host: str
    capabilities: frozenset[str] = frozenset()
    tool_aliases: Mapping[str, str] = field(default_factory=dict)
    observed_capabilities: frozenset[str] | None = None
    source: str = "expected-profile"

    @property
    def is_attested(self) -> bool:
        return self.observed_capabilities is not None

    def supports(self, capability: str, *, authoritative: bool = False) -> bool:
        available = self.observed_capabilities if self.is_attested else self.capabilities
        return capability in available and (not authoritative or self.is_attested)

    def normalize(self, tool_name: str) -> str:
        return self.tool_aliases.get(tool_name, tool_name)

    def attest(self, observed: Iterable[str], source: str = "host-probe") -> "HostCapabilities":
        """Return a runtime-authoritative profile from actual probe results."""
        observed_set = frozenset(str(item).strip() for item in observed if str(item).strip())
        return HostCapabilities(
            host=self.host,
            capabilities=self.capabilities,
            tool_aliases=self.tool_aliases,
            observed_capabilities=observed_set,
            source=source,
        )

    def compatibility_report(self, required: Iterable[str]) -> dict[str, object]:
        required_set = set(required)
        expected = required_set & self.capabilities
        available_set = self.observed_capabilities if self.is_attested else self.capabilities
        available = required_set & available_set
        missing = required_set - available_set
        return {
            "host": self.host,
            "compatible": self.is_attested and not missing,
            "authoritative": self.is_attested,
            "capabilities_source": self.source,
            "required": sorted(required_set),
            "expected": sorted(expected),
            "available": sorted(available),
            "missing": sorted(missing),
        }


# These are conservative *expected* profiles. Real adapters must call
# ``attest`` after probing the host; expected capabilities are never
# runtime-authoritative.
HOST_PROFILES: dict[str, HostCapabilities] = {
    "generic-mcp-host": HostCapabilities(
        "generic-mcp-host",
        frozenset({"inspect_files", "execute_command", "edit_files", "run_tests"}),
        {"tools/call": "route_tool"},
    ),
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
    """Return a conservative profile; aliases resolve to canonical profiles."""
    key = host.strip().lower()
    if not key:
        raise ValueError("host must be a non-empty string")
    aliases = {"claude": "claude-code", "cc": "claude-code", "agy": "antigravity",
               "antigravity": "antigravity", "codex": "codex"}
    key = aliases.get(key, key)
    return HOST_PROFILES.get(key, HostCapabilities(key))
