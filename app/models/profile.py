"""Profile data model.

A :class:`Profile` groups projects (Frontend, Backend, AI, Trading, ...)
so they can be started or stopped together with one action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from app.utils.helpers import new_id, now_iso

# Suggested accent colors for profile cards (UI presets).
PROFILE_COLORS: List[str] = [
    "#6366f1", "#8b5cf6", "#ec4899", "#f43f5e", "#f59e0b",
    "#10b981", "#14b8a6", "#0ea5e9", "#64748b",
]

# Profile seeds created on first launch, mirroring common developer workflows.
DEFAULT_PROFILES: List[dict] = [
    {"name": "Frontend", "description": "React / Next / Vue apps and design systems", "color": "#61dafb"},
    {"name": "Backend", "description": "APIs, workers and mock databases", "color": "#10b981"},
    {"name": "AI", "description": "Model training, notebooks and inference services", "color": "#8b5cf6"},
    {"name": "Trading", "description": "Bots, market data feeds and backtests", "color": "#f59e0b"},
    {"name": "Personal", "description": "Side projects and experiments", "color": "#ec4899"},
]


@dataclass
class Profile:
    """A named group of projects with bulk lifecycle actions."""

    name: str
    id: str = field(default_factory=new_id)
    description: str = ""
    color: str = "#6366f1"
    project_ids: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        """Serialize for JSON storage."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "color": self.color,
            "project_ids": list(self.project_ids),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        """Build a Profile from stored JSON with safe defaults."""
        if not isinstance(data, dict):
            raise ValueError("Profile record must be a JSON object.")
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValueError("Profile record is missing 'name'.")
        profile = cls(
            id=str(data.get("id") or new_id()),
            name=name,
            description=str(data.get("description") or ""),
            color=str(data.get("color") or "#6366f1"),
            project_ids=[str(p) for p in (data.get("project_ids") or [])],
            created_at=str(data.get("created_at") or now_iso()),
            updated_at=str(data.get("updated_at") or now_iso()),
        )
        return profile

    def touch(self) -> None:
        self.updated_at = now_iso()

    def contains(self, project_id: str) -> bool:
        return project_id in self.project_ids
