"""Data model package: Project, Profile and AppSettings."""

from app.models.profile import PROFILE_COLORS, DEFAULT_PROFILES, Profile  # noqa: F401
from app.models.project import Project, ProjectStatus, type_meta  # noqa: F401
from app.models.settings import ACCENTS, AppSettings  # noqa: F401
