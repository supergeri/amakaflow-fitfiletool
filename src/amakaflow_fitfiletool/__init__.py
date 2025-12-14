"""
AmakaFlow FIT File Tool

Single source of truth for:
- Exercise → Garmin category mapping
- FIT file generation
- Preview step generation
"""

from .garmin_lookup import GarminExerciseLookup
from .fit_builder import (
    build_fit_workout,
    blocks_to_steps,
    detect_sport_type,
    get_fit_metadata,
)
from .preview import get_preview_steps

__version__ = "0.1.0"

__all__ = [
    "GarminExerciseLookup",
    "build_fit_workout",
    "blocks_to_steps",
    "detect_sport_type",
    "get_fit_metadata",
    "get_preview_steps",
]
