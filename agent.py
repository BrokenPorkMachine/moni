"""Agent identity and capability contract for future coordinator mode."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentInfo:
    name: str
    version: str
    capabilities: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "capabilities": list(self.capabilities),
        }


def local_agent(name: str = "local") -> AgentInfo:
    if not name.strip():
        raise ValueError("agent name must be non-empty")
    return AgentInfo(
        name=name,
        version="0.1.0",
        capabilities=("http", "tcp", "history", "webhook"),
    )
