"""
AmakaFlow FIT File Tool

Single source of truth for:
- Exercise -> Garmin category mapping
- FIT file generation
- FIT file parsing and preview
- Sport display constants
"""

from .garmin_lookup import GarminExerciseLookup
from .fit_builder import (
    build_fit_workout,
    blocks_to_steps,
    detect_sport_type,
    get_fit_metadata,
)
from .preview import get_preview_steps

# FIT file parsing (requires fitparse)
from .fit_parser import (
    parse_fit_file,
    validate_fit_file,
    get_sport_display,
    get_sport_color,
    format_duration,
    format_distance,
    SPORT_COLORS,
    SPORT_DISPLAY_NAMES,
    SUB_SPORT_DISPLAY_NAMES,
    EXERCISE_CATEGORY_NAMES,
)

__version__ = "0.2.3"

__all__ = [
    # Exercise lookup
    "GarminExerciseLookup",
    # FIT file generation
    "build_fit_workout",
    "blocks_to_steps",
    "detect_sport_type",
    "get_fit_metadata",
    "get_preview_steps",
    # FIT file parsing
    "parse_fit_file",
    "validate_fit_file",
    # Display helpers
    "get_sport_display",
    "get_sport_color",
    "format_duration",
    "format_distance",
    # Constants
    "SPORT_COLORS",
    "SPORT_DISPLAY_NAMES",
    "SUB_SPORT_DISPLAY_NAMES",
    "EXERCISE_CATEGORY_NAMES",
]
