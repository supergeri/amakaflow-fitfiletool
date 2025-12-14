"""
FIT File Parser Module

Parses existing FIT workout files and returns structured data for preview.
Requires fitparse library: pip install fitparse
"""

from typing import Dict, Any, List, Optional, Tuple


# ============================================================================
# Sport Display Constants
# ============================================================================

SPORT_COLORS = {
    'running': '#22c55e',
    'cycling': '#f97316',
    'swimming': '#3b82f6',
    'strength_training': '#ef4444',
    'training': '#8b5cf6',
    'walking': '#84cc16',
    'hiking': '#a3e635',
    'fitness_equipment': '#06b6d4',
}

SPORT_DISPLAY_NAMES = {
    'fitness_equipment': 'Cardio',
    'training': 'Strength',
    'running': 'Running',
    'cycling': 'Cycling',
    'swimming': 'Swimming',
    'walking': 'Walking',
    'hiking': 'Hiking',
}

SUB_SPORT_DISPLAY_NAMES = {
    'strength_training': 'Strength',
    'generic': None,  # Use sport name instead
    'cardio_training': 'Cardio',
    'hiit': 'HIIT',
    'indoor_cycling': 'Indoor Cycling',
    'indoor_running': 'Treadmill',
    'lap_swimming': 'Lap Swimming',
    'open_water': 'Open Water',
}

DEFAULT_SPORT_COLOR = '#6b7280'


# ============================================================================
# Display Helper Functions
# ============================================================================

def get_sport_display(sport: Optional[str], sub_sport: Optional[str] = None) -> str:
    """
    Get human-readable display name for a sport/sub_sport combination.

    Args:
        sport: FIT sport type string (e.g., 'fitness_equipment', 'training')
        sub_sport: Optional FIT sub_sport type string (e.g., 'strength_training')

    Returns:
        Human-readable display name string
    """
    # Prefer sub_sport if it has a meaningful display name
    if sub_sport and sub_sport in SUB_SPORT_DISPLAY_NAMES:
        display = SUB_SPORT_DISPLAY_NAMES[sub_sport]
        if display is not None:
            return display

    # Check if sub_sport is not generic and not in our mapping - use it as-is
    if sub_sport and sub_sport != 'generic' and sub_sport not in SUB_SPORT_DISPLAY_NAMES:
        return sub_sport.replace('_', ' ').title()

    # Fall back to sport display name
    if sport and sport in SPORT_DISPLAY_NAMES:
        return SPORT_DISPLAY_NAMES[sport]

    # Last resort - format the sport string
    return sport.replace('_', ' ').title() if sport else 'Workout'


def get_sport_color(sport: Optional[str], sub_sport: Optional[str] = None) -> str:
    """
    Get badge color for a sport/sub_sport combination.

    Args:
        sport: FIT sport type string
        sub_sport: Optional FIT sub_sport type string

    Returns:
        Hex color string (e.g., '#22c55e')
    """
    # Use sub_sport color if it's strength training
    if sub_sport == 'strength_training':
        return SPORT_COLORS.get('strength_training', DEFAULT_SPORT_COLOR)

    # Use sport color
    return SPORT_COLORS.get(sport, DEFAULT_SPORT_COLOR) if sport else DEFAULT_SPORT_COLOR


def format_duration(seconds: float) -> str:
    """
    Format duration in seconds to human-readable string.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted string like "1:30" or "45s"
    """
    if not seconds or seconds <= 0:
        return ""

    seconds = int(seconds)
    if seconds >= 3600:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}:{mins:02d}:00"
    elif seconds >= 60:
        mins = seconds // 60
        secs = seconds % 60
        if secs > 0:
            return f"{mins}:{secs:02d}"
        return f"{mins} min"
    else:
        return f"{seconds}s"


def format_distance(meters: float) -> str:
    """
    Format distance in meters to human-readable string.

    Args:
        meters: Distance in meters

    Returns:
        Formatted string like "500m" or "1.5km"
    """
    if not meters or meters <= 0:
        return ""

    if meters >= 1000:
        km = meters / 1000
        if km == int(km):
            return f"{int(km)}km"
        return f"{km:.1f}km"
    return f"{int(meters)}m"


# ============================================================================
# Exercise Name Constants
# ============================================================================

# Garmin exercise category names (from FIT SDK)
EXERCISE_CATEGORY_NAMES = {
    0: "Bench Press", 1: "Calf Raise", 2: "Cardio", 3: "Carry", 4: "Chop",
    5: "Core", 6: "Crunch", 7: "Curl", 8: "Deadlift", 9: "Flye",
    10: "Hip Raise", 11: "Hip Stability", 12: "Hip Swing", 13: "Hyperextension",
    14: "Lateral Raise", 15: "Leg Curl", 16: "Leg Raise", 17: "Lunge",
    18: "Olympic Lift", 19: "Plank", 20: "Plyo", 21: "Pull Up", 22: "Push Up",
    23: "Row", 24: "Shoulder Press", 25: "Shoulder Stability", 26: "Shrug",
    27: "Sit Up", 28: "Squat", 29: "Total Body", 30: "Triceps Extension",
    31: "Warm Up", 32: "Run",
}


# ============================================================================
# FIT File Parser
# ============================================================================

def parse_fit_file(filepath: str) -> Optional[Dict[str, Any]]:
    """
    Parse a FIT workout file and return structured data for preview.

    Args:
        filepath: Path to the FIT file

    Returns:
        Dictionary with workout data, or None if parsing fails.

        Structure:
        {
            'name': str,           # Workout name
            'sport': str,          # FIT sport type
            'sub_sport': str,      # FIT sub_sport type
            'sport_display': str,  # Human-readable sport name
            'sport_color': str,    # Badge color hex
            'source': str,         # Source app (e.g., "Garmin Connect")
            'manufacturer': str,   # Device manufacturer
            'created': str,        # Creation date string
            'steps': List[Dict],   # List of exercise steps
        }

        Each step contains:
        {
            'name': str,           # Exercise name
            'category': str,       # Exercise category
            'exercise_id': int,    # FIT exercise_name ID
            'duration_type': str,  # 'reps', 'time', 'distance', 'open'
            'reps': int,           # Rep count (if duration_type is reps)
            'duration': float,     # Duration in seconds
            'distance': float,     # Distance in meters
            'intensity': str,      # 'active', 'rest', 'warmup', 'cooldown'
            'step_type': str,      # 'active', 'rest', 'warmup', 'cooldown'
            'is_rest': bool,       # True if rest step
            'is_repeat': bool,     # True if repeat step
            'repeat_count': int,   # Number of repeats
            'sets': int,           # Number of sets (calculated)
            'weight': float,       # Weight if specified
            'weight_unit': str,    # 'kg' or 'lb'
            'notes': str,          # Step notes
        }
    """
    try:
        from fitparse import FitFile
    except ImportError:
        return None

    try:
        fitfile = FitFile(filepath)

        workout_data = {
            'name': 'Workout',
            'sport': None,
            'sub_sport': None,
            'steps': [],
            'created': None,
            'source': None,
            'manufacturer': None,
        }

        # ----------------------------------------------------------------
        # Get file metadata
        # ----------------------------------------------------------------
        for record in fitfile.get_messages('file_id'):
            for field in record.fields:
                if field.name == 'time_created' and field.value:
                    workout_data['created'] = str(field.value)
                elif field.name == 'manufacturer' and field.value:
                    workout_data['manufacturer'] = str(field.value)
                elif field.name == 'garmin_product' and field.value:
                    workout_data['source'] = str(field.value).replace('_', ' ').title()

        # ----------------------------------------------------------------
        # First pass: collect exercise titles for lookup (strength workouts)
        # ----------------------------------------------------------------
        exercise_titles = {}
        for record in fitfile.get_messages('exercise_title'):
            title_data = {}
            for field in record.fields:
                if field.name == 'wkt_step_name':
                    title_data['name'] = field.value
                elif field.name == 'exercise_category':
                    title_data['category'] = str(field.value) if field.value else None
                elif field.name == 'exercise_name':
                    title_data['exercise_id'] = field.value

            if title_data.get('category') and title_data.get('name'):
                key = (title_data.get('category'), title_data.get('exercise_id'))
                exercise_titles[key] = title_data['name']
                exercise_titles[title_data.get('category')] = title_data['name']

        # ----------------------------------------------------------------
        # Get workout name and sport type
        # ----------------------------------------------------------------
        for record in fitfile.get_messages('workout'):
            for field in record.fields:
                if field.name == 'wkt_name' and field.value:
                    workout_data['name'] = field.value
                elif field.name == 'sport' and field.value:
                    workout_data['sport'] = str(field.value)
                elif field.name == 'sub_sport' and field.value:
                    workout_data['sub_sport'] = str(field.value)

        # ----------------------------------------------------------------
        # Second pass: get workout steps
        # ----------------------------------------------------------------
        steps_raw = []
        for record in fitfile.get_messages('workout_step'):
            step = {'is_rest': False, 'is_repeat': False}
            for field in record.fields:
                if field.name == 'wkt_step_name' and field.value:
                    step['name'] = field.value
                elif field.name == 'exercise_category' and field.value:
                    step['category'] = str(field.value)
                elif field.name == 'exercise_name':
                    step['exercise_id'] = field.value
                elif field.name == 'duration_type':
                    step['duration_type'] = str(field.value)
                elif field.name == 'duration_reps' and field.value:
                    step['reps'] = int(field.value)
                elif field.name == 'duration_time' and field.value:
                    step['duration'] = float(field.value)
                elif field.name == 'duration_distance' and field.value:
                    step['distance'] = float(field.value)
                elif field.name == 'intensity':
                    intensity = str(field.value) if field.value else None
                    step['intensity'] = intensity
                    if intensity == 'rest':
                        step['is_rest'] = True
                elif field.name == 'repeat_steps' and field.value:
                    step['is_repeat'] = True
                    step['repeat_count'] = int(field.value)
                elif field.name == 'exercise_weight' and field.value:
                    step['weight'] = float(field.value)
                elif field.name == 'weight_display_unit':
                    step['weight_unit'] = str(field.value) if field.value else 'kg'
                elif field.name == 'notes' and field.value:
                    step['notes'] = field.value
                elif field.name == 'target_type' and field.value:
                    step['target_type'] = str(field.value)
                elif field.name == 'target_value' and field.value:
                    step['target_value'] = field.value

            steps_raw.append(step)

        # ----------------------------------------------------------------
        # Determine if cardio vs strength workout
        # ----------------------------------------------------------------
        sport_lower = (workout_data.get('sport') or '').lower()
        sub_sport_lower = (workout_data.get('sub_sport') or '').lower()
        cardio_sports = ['running', 'cycling', 'swimming', 'walking', 'hiking',
                        'run', 'bike', 'swim', 'walk', 'hike', 'cardio',
                        'trail_running', 'treadmill']
        is_cardio = any(c in sport_lower for c in cardio_sports) or any(c in sub_sport_lower for c in cardio_sports)
        is_strength = ('training' in sport_lower or 'strength' in sub_sport_lower) and not is_cardio

        # ----------------------------------------------------------------
        # Process steps with repeat handling
        # ----------------------------------------------------------------
        processed_steps = []
        i = 0
        while i < len(steps_raw):
            step = steps_raw[i].copy()

            # Skip repeat markers (they just indicate looping back)
            if step.get('is_repeat'):
                i += 1
                continue

            # Get exercise name from various sources
            if not step.get('name'):
                category = step.get('category')
                exercise_id = step.get('exercise_id')

                # Try exercise_titles lookup first
                if category:
                    key = (category, exercise_id)
                    if key in exercise_titles:
                        step['name'] = exercise_titles[key]
                    elif category in exercise_titles:
                        step['name'] = exercise_titles[category]

                # Fall back to category name
                if not step.get('name') and category:
                    try:
                        cat_id = int(category)
                        step['name'] = EXERCISE_CATEGORY_NAMES.get(cat_id, f"Exercise {cat_id}")
                    except (ValueError, TypeError):
                        step['name'] = str(category).replace('_', ' ').title()

            # Determine step type
            intensity = step.get('intensity', 'active')
            if intensity == 'rest':
                step['step_type'] = 'rest'
            elif intensity == 'warmup':
                step['step_type'] = 'warmup'
            elif intensity == 'cooldown':
                step['step_type'] = 'cooldown'
            else:
                step['step_type'] = 'active'

            # Check if next step is a repeat that references this step
            sets = 1
            if i + 2 < len(steps_raw):
                potential_rest = steps_raw[i + 1]
                potential_repeat = steps_raw[i + 2]
                if potential_rest.get('is_rest') and potential_repeat.get('is_repeat'):
                    sets = potential_repeat.get('repeat_count', 0) + 1
                    step['sets'] = sets
                    i += 2  # Skip rest and repeat

            if 'sets' not in step:
                step['sets'] = 1

            processed_steps.append(step)
            i += 1

        workout_data['steps'] = processed_steps

        # ----------------------------------------------------------------
        # Add computed display fields
        # ----------------------------------------------------------------
        workout_data['sport_display'] = get_sport_display(
            workout_data['sport'],
            workout_data['sub_sport']
        )
        workout_data['sport_color'] = get_sport_color(
            workout_data['sport'],
            workout_data['sub_sport']
        )

        return workout_data

    except Exception as e:
        return None


def validate_fit_file(filepath: str) -> Dict[str, Any]:
    """
    Validate a FIT workout file for compatibility issues.

    Args:
        filepath: Path to the FIT file

    Returns:
        Dictionary with:
        {
            'valid': bool,        # True if no issues found
            'issues': List[str],  # List of issue descriptions
            'warnings': List[str] # List of warnings (non-critical)
        }
    """
    result = {
        'valid': True,
        'issues': [],
        'warnings': []
    }

    workout_data = parse_fit_file(filepath)
    if not workout_data:
        result['valid'] = False
        result['issues'].append("Could not parse FIT file")
        return result

    # Check for invalid exercise categories (33+)
    for step in workout_data.get('steps', []):
        category = step.get('category')
        if category:
            try:
                cat_id = int(category)
                if cat_id > 32:
                    result['valid'] = False
                    result['issues'].append(
                        f"Invalid exercise category {cat_id} in '{step.get('name', 'Unknown')}'. "
                        "Some Garmin watches may reject this workout."
                    )
            except (ValueError, TypeError):
                pass

    # Check sport type
    sport = workout_data.get('sport')
    sub_sport = workout_data.get('sub_sport')
    if sport == 'fitness_equipment' and sub_sport == 'generic':
        result['warnings'].append(
            "Workout uses generic sport type. Consider using 'training/strength_training' "
            "for better Garmin watch compatibility."
        )

    return result
