"""
Garmin Exercise Lookup Module

Maps exercise names to valid FIT SDK exercise categories.

IMPORTANT: Only uses valid FIT SDK categories (0-32).
Categories 33+ are extended and may cause Garmin watches to reject workouts.
"""

import json
import re
from pathlib import Path
from difflib import SequenceMatcher
from typing import Dict, Any, Optional


# Maximum valid FIT SDK exercise category ID
# Categories 0-32 are standard FIT SDK categories
# Categories 33+ are extended and may not work on all Garmin watches
MAX_VALID_CATEGORY_ID = 32

# Fallback remapping for invalid categories
# Maps invalid category IDs to valid FIT SDK categories
INVALID_CATEGORY_FALLBACK = {
    33: 2,   # Map to Cardio
    34: 2,   # Map to Cardio
    35: 2,   # Map to Cardio
    36: 2,   # Map to Cardio
    37: 2,   # Map to Cardio
    38: 2,   # Indoor Rower -> Cardio (Row 23 doesn't work for erg machines)
    39: 29,  # Map to Total Body
    40: 29,  # Map to Total Body
    41: 29,  # Map to Total Body
    42: 29,  # Map to Total Body
    43: 29,  # Map to Total Body
}


def validate_category_id(category_id: int, exercise_name: Optional[str] = None) -> int:
    """
    Validate and remap exercise category ID to ensure Garmin compatibility.

    FIT SDK only defines categories 0-32 as standard. Extended categories (33+)
    may cause the watch to reject the entire workout.

    Returns a valid category ID (0-32).
    """
    if category_id <= MAX_VALID_CATEGORY_ID:
        return category_id

    # Check for specific remapping
    if category_id in INVALID_CATEGORY_FALLBACK:
        return INVALID_CATEGORY_FALLBACK[category_id]

    # Default fallback for any unknown invalid category
    # Total Body (29) is a safe generic choice
    return 29


class GarminExerciseLookup:
    """
    Lookup Garmin exercise categories from exercise names.

    Uses:
    1. Built-in keywords for common exercises (highest priority)
    2. Exact match from exercises database
    3. Keyword matching from database
    4. Fuzzy matching as fallback
    5. Default to Core (5) if no match
    """

    def __init__(self, data_path: Optional[str] = None):
        if data_path is None:
            data_path = Path(__file__).parent / "garmin_exercises.json"

        with open(data_path) as f:
            data = json.load(f)

        self.categories = data["categories"]
        self.exercises = data["exercises"]
        self.keywords = data.get("keywords", {}).get("en", {})

        # Built-in keywords for common exercises
        # IMPORTANT: Only use VALID FIT SDK exercise categories!
        # Valid categories: 0=bench_press, 2=cardio, 5=core, 6=crunch, 17=lunge,
        # 19=plank, 21=pull_up, 22=push_up, 23=row, 28=squat, 29=total_body, etc.
        # Category 38 is INVALID and will cause watch to reject workout!
        # NOTE: Run uses Cardio (2) for mixed workouts - Run (32) only works with sport type 1
        self.builtin_keywords = {
            "run": {"category_id": 2, "category_key": "CARDIO", "category_name": "Cardio", "display_name": "Run"},
            "running": {"category_id": 2, "category_key": "CARDIO", "category_name": "Cardio", "display_name": "Run"},
            "jog": {"category_id": 2, "category_key": "CARDIO", "category_name": "Cardio", "display_name": "Run"},
            "sprint": {"category_id": 2, "category_key": "CARDIO", "category_name": "Cardio", "display_name": "Run"},
            "ski erg": {"category_id": 2, "category_key": "CARDIO", "category_name": "Cardio", "display_name": "Ski Erg"},
            "ski mogul": {"category_id": 2, "category_key": "CARDIO", "category_name": "Cardio", "display_name": "Ski Erg"},
            "ski": {"category_id": 2, "category_key": "CARDIO", "category_name": "Cardio", "display_name": "Ski Erg"},
            "row erg": {"category_id": 23, "category_key": "ROW", "category_name": "Row", "display_name": "Row"},
            "rower": {"category_id": 23, "category_key": "ROW", "category_name": "Row", "display_name": "Row"},
            "indoor row": {"category_id": 23, "category_key": "ROW", "category_name": "Row", "display_name": "Indoor Row"},
            "assault bike": {"category_id": 2, "category_key": "CARDIO", "category_name": "Cardio", "display_name": "Assault Bike"},
            "echo bike": {"category_id": 2, "category_key": "CARDIO", "category_name": "Cardio", "display_name": "Echo Bike"},
            "air bike": {"category_id": 2, "category_key": "CARDIO", "category_name": "Cardio", "display_name": "Air Bike"},
            "bike erg": {"category_id": 2, "category_key": "CARDIO", "category_name": "Cardio", "display_name": "Bike Erg"},
            "burpee": {"category_id": 29, "category_key": "TOTAL_BODY", "category_name": "Total Body", "display_name": "Burpee"},
            "wall ball": {"category_id": 28, "category_key": "SQUAT", "category_name": "Squat", "display_name": "Wall Ball"},
        }

        # Build reverse lookup: category_name -> category_id
        self.category_ids = {
            v["name"]: v["id"] for v in self.categories.values()
        }

    def normalize(self, name: str) -> str:
        """Normalize exercise name for matching."""
        name = name.lower().strip()
        # Remove trailing pipe characters that may come from canonical format parsing
        name = name.rstrip('|').strip()

        # Remove common prefixes like A1:, B2;, etc
        name = re.sub(r'^[a-z]\d+[;:\s]+', '', name, flags=re.IGNORECASE)

        # Remove equipment prefixes
        for prefix in ['db ', 'kb ', 'bb ', 'sb ', 'mb ', 'trx ', 'cable ', 'band ']:
            if name.startswith(prefix):
                name = name[len(prefix):]

        # Remove rep counts like x10, X8
        name = re.sub(r'\s*x\s*\d+.*$', '', name, flags=re.IGNORECASE)

        # Remove "each side", "per side", etc
        name = re.sub(r'\s+(each|per)\s+(side|arm|leg).*$', '', name, flags=re.IGNORECASE)

        # Remove distance at END like "200m", "1km", "1.5 km"
        name = re.sub(r'\s*[\d.]+\s*(m|km)\s*$', '', name, flags=re.IGNORECASE)

        # Remove distance at START like "1km Run", "500m Row"
        name = re.sub(r'^[\d.]+\s*(m|km)\s+', '', name, flags=re.IGNORECASE)

        return name.strip()

    def find(self, exercise_name: str, lang: str = "en") -> Dict[str, Any]:
        """
        Find the best matching Garmin category for an exercise name.

        Returns dict with:
            - category_id: FIT SDK category ID (validated to 0-32)
            - category_key: Garmin category key (e.g. PUSH_UP)
            - category_name: Display name (e.g. Push Up)
            - exercise_key: Garmin exercise key if exact match found
            - display_name: Garmin display name if exact match found
            - match_type: "builtin_keyword", "exact", "keyword", "fuzzy", or "default"
        """
        normalized = self.normalize(exercise_name)

        # 1. Check builtin keywords FIRST (these override exact matches for compatibility)
        # This ensures "run" maps to Cardio (2) for mixed workouts, not Run (32)
        for keyword, info in self.builtin_keywords.items():
            if keyword in normalized:
                return {
                    "category_id": info["category_id"],
                    "category_key": info["category_key"],
                    "category_name": info["category_name"],
                    "exercise_key": None,
                    "display_name": info.get("display_name"),
                    "match_type": "builtin_keyword",
                    "matched_keyword": keyword,
                    "input": exercise_name,
                    "normalized": normalized
                }

        # 2. Try exact match in exercises
        if normalized in self.exercises:
            result = self.exercises[normalized].copy()
            result["match_type"] = "exact"
            result["input"] = exercise_name
            result["normalized"] = normalized
            # Validate category ID
            result["category_id"] = validate_category_id(result["category_id"], exercise_name)
            return result

        # 3. Try JSON keyword matching
        keywords = self.keywords if lang == "en" else {}
        for keyword, info in keywords.items():
            if keyword in normalized:
                category_id = validate_category_id(info["category_id"], exercise_name)
                return {
                    "category_id": category_id,
                    "category_key": info["category_key"],
                    "category_name": info["category_name"],
                    "exercise_key": None,
                    "display_name": info.get("display_name"),
                    "match_type": "keyword",
                    "matched_keyword": keyword,
                    "input": exercise_name,
                    "normalized": normalized
                }

        # 4. Try fuzzy matching against exercises
        best_match = None
        best_ratio = 0.0

        for ex_name, ex_info in self.exercises.items():
            ratio = SequenceMatcher(None, normalized, ex_name).ratio()
            if ratio > best_ratio and ratio > 0.6:
                best_ratio = ratio
                best_match = ex_info

        if best_match:
            result = best_match.copy()
            result["match_type"] = "fuzzy"
            result["match_ratio"] = best_ratio
            result["input"] = exercise_name
            result["normalized"] = normalized
            # Validate category ID
            result["category_id"] = validate_category_id(result["category_id"], exercise_name)
            return result

        # 5. Default fallback
        return {
            "category_id": 5,  # Core
            "category_key": "CORE",
            "category_name": "Core",
            "exercise_key": None,
            "display_name": None,
            "match_type": "default",
            "input": exercise_name,
            "normalized": normalized
        }

    def get_category_id(self, category_name: str) -> int:
        """Get category ID by name."""
        return self.category_ids.get(category_name, 5)  # Default to Core


# Module-level singleton
_lookup = None

def get_lookup(data_path: Optional[str] = None) -> GarminExerciseLookup:
    """Get the singleton GarminExerciseLookup instance."""
    global _lookup
    if _lookup is None:
        _lookup = GarminExerciseLookup(data_path)
    return _lookup
