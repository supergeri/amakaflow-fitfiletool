"""
FIT File Builder Module

Generates Garmin-compatible FIT workout files using the fit_tool library.
This is the single source of truth for FIT file generation.
"""

import re
import os
import tempfile
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional, Set

from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.workout_message import WorkoutMessage
from fit_tool.profile.messages.workout_step_message import WorkoutStepMessage
from fit_tool.profile.messages.exercise_title_message import ExerciseTitleMessage
from fit_tool.profile.profile_type import (
    Sport,
    SubSport,
    Intensity,
    WorkoutStepDuration,
    WorkoutStepTarget,
    Manufacturer,
    FileType,
)

from .garmin_lookup import get_lookup, validate_category_id


def _is_user_confirmed_name(name: str) -> bool:
    """
    Check if the input name looks like a user-confirmed Garmin exercise name.

    User-confirmed names are typically:
    - Title Case (e.g., "Burpee Box Jump", "Wall Ball")
    - Don't have distance prefixes (e.g., "500m", "1km")
    - Don't have rep counts (e.g., "x10")

    Returns True if the name should be preserved as-is (user confirmed),
    False if it should go through the normal lookup mapping.
    """
    if not name or len(name) < 2:
        return False

    # Check for distance prefix (e.g., "500m Run", "1km Row")
    if re.match(r'^[\d.]+\s*(m|km|mi)\s+', name, re.IGNORECASE):
        return False

    # Check for rep/set counts (e.g., "Push Up x10", "Squat 3x10")
    if re.search(r'\s*\d*x\d+', name, re.IGNORECASE):
        return False

    # Check if it looks like Title Case (first letter of most words capitalized)
    # This indicates a user has selected/confirmed a specific exercise name
    words = name.split()
    if len(words) == 0:
        return False

    # Count words that start with uppercase
    capitalized = sum(1 for w in words if w[0].isupper())

    # If most words are capitalized, it's likely a user-confirmed name
    # Allow for small words like "to", "of", "the" which might be lowercase
    return capitalized >= len(words) * 0.6


def parse_structure(structure_str: Optional[str]) -> int:
    """Parse structure string like '3 rounds' to get count."""
    if not structure_str:
        return 1
    match = re.search(r'(\d+)', structure_str)
    return int(match.group(1)) if match else 1


def _create_rest_step(duration_sec: int, rest_type: str = 'timed') -> Dict[str, Any]:
    """
    Create a rest step for FIT file.

    Args:
        duration_sec: Rest duration in seconds (ignored if rest_type='button')
        rest_type: 'timed' for countdown timer, 'button' for lap button press

    Returns:
        dict: Rest step data
    """
    if rest_type == 'button':
        # OPEN = lap button press - user presses lap when done
        return {
            'type': 'rest',
            'display_name': 'Rest',
            'intensity': 'rest',
            'duration_type': 'lap_button',
            'duration_value': 0,
            'rest_seconds': 0,
        }
    else:
        # Timed rest with countdown
        return {
            'type': 'rest',
            'display_name': 'Rest',
            'intensity': 'rest',
            'duration_type': 'time',
            'duration_value': int(duration_sec * 1000),
            'rest_seconds': duration_sec,
        }


def blocks_to_steps(
    blocks_json: Dict[str, Any],
    use_lap_button: bool = False
) -> Tuple[List[Dict[str, Any]], Set[int]]:
    """
    Convert blocks JSON to FIT workout steps.

    Supports auto-rest insertion at three levels:
    1. After each exercise: Uses exercise.rest_sec
    2. After each superset: Uses superset.rest_between_sec
    3. After each block: Uses block.rest_between_rounds_sec

    Rest can be timed (countdown) or button-press (lap button).
    Set rest_type='button' on exercise/superset/block for lap button rest.

    Args:
        blocks_json: Workout data with blocks/exercises
        use_lap_button: If True, use "lap button press" for all exercises

    Returns:
        Tuple of (steps list, set of category IDs used)
    """
    lookup = get_lookup()
    steps = []
    category_ids_used: Set[int] = set()

    blocks = blocks_json.get('blocks', [])
    num_blocks = len(blocks)

    for block_idx, block in enumerate(blocks):
        rounds = parse_structure(block.get('structure'))
        # Legacy: rest_between_sec was used for intra-set rest
        rest_between_sets = block.get('rest_between_sets_sec') or block.get('rest_between_sec', 30) or 30
        # New: rest_between_rounds_sec for rest after the entire block
        rest_after_block = block.get('rest_between_rounds_sec')
        rest_type_block = block.get('rest_type', 'timed')

        is_last_block = (block_idx == num_blocks - 1)

        all_exercises = []
        supersets = block.get('supersets', [])

        # Process supersets with their rest settings
        for superset_idx, superset in enumerate(supersets):
            superset_exercises = superset.get('exercises', [])
            superset_rest = superset.get('rest_between_sec')
            superset_rest_type = superset.get('rest_type', 'timed')
            is_last_superset = (superset_idx == len(supersets) - 1) and not block.get('exercises')

            for ex_idx, exercise in enumerate(superset_exercises):
                exercise['_superset_idx'] = superset_idx
                exercise['_is_last_in_superset'] = (ex_idx == len(superset_exercises) - 1)
                exercise['_superset_rest'] = superset_rest
                exercise['_superset_rest_type'] = superset_rest_type
                exercise['_is_last_superset'] = is_last_superset
                all_exercises.append(exercise)

        # Process standalone exercises
        standalone_exercises = block.get('exercises', [])
        for ex_idx, exercise in enumerate(standalone_exercises):
            exercise['_superset_idx'] = None
            exercise['_is_last_in_superset'] = False
            exercise['_superset_rest'] = None
            exercise['_superset_rest_type'] = 'timed'
            exercise['_is_last_superset'] = (ex_idx == len(standalone_exercises) - 1)
            all_exercises.append(exercise)

        for exercise in all_exercises:
            name = exercise.get('name', 'Exercise')
            reps_raw = exercise.get('reps')  # Don't default - None means no reps specified
            reps_range = exercise.get('reps_range')  # e.g., "6-8", "8-10"
            sets = exercise.get('sets') or rounds
            duration_sec = exercise.get('duration_sec')
            distance_m = exercise.get('distance_m')  # Numeric distance in meters from ingestor

            match = lookup.find(name)
            raw_category_id = match['category_id']
            # Validate category ID - remap invalid (33+) to valid (0-32)
            category_id = validate_category_id(raw_category_id, name)
            category_ids_used.add(category_id)

            # IMPORTANT: If the input name is an exact match in the Garmin database,
            # use the DB's display_name. This preserves the canonical Garmin name.
            # If not an exact match, check if the input name looks like a user-confirmed
            # Garmin name (Title Case, no distance prefixes) and use it directly.
            # This preserves user-confirmed mappings like "Burpee Box Jump".
            if match.get('match_type') == 'exact' or match.get('match_type') == 'exact_with_category_override':
                display_name = match.get('display_name') or name
            elif _is_user_confirmed_name(name):
                # Input looks like a user-confirmed Garmin name - preserve it
                display_name = name
            else:
                display_name = match.get('display_name') or match['category_name']

            # Determine duration type and value
            # FIT duration types: 0=time(ms), 1=lap_button, 3=distance(cm), 29=reps
            duration_type = "reps"
            duration_value = 10

            if use_lap_button:
                duration_type = "lap_button"
                duration_value = 0
            else:
                # Check for distance - first from distance_m field, then from reps string
                distance_meters = None

                # Priority 1: Use numeric distance_m field from ingestor (e.g., 500 for 500m)
                if distance_m is not None and distance_m > 0:
                    distance_meters = float(distance_m)
                # Priority 2: Parse distance from reps string (e.g., "500m", "1km")
                elif isinstance(reps_raw, str):
                    reps_str = reps_raw.lower().strip()
                    km_match = re.match(r'^([\d.]+)\s*km$', reps_str)
                    m_match = re.match(r'^([\d.]+)\s*m$', reps_str)
                    if km_match:
                        distance_meters = float(km_match.group(1)) * 1000
                    elif m_match:
                        distance_meters = float(m_match.group(1))

                if distance_meters is not None:
                    duration_type = "distance"
                    duration_value = int(distance_meters * 100)  # convert to cm
                elif duration_sec:
                    duration_type = "time"
                    duration_value = int(duration_sec * 1000)  # convert to ms
                elif reps_raw is not None:
                    # Reps were explicitly specified
                    duration_type = "reps"
                    if isinstance(reps_raw, str):
                        try:
                            duration_value = int(reps_raw.split('-')[0])
                        except:
                            duration_value = 10
                    else:
                        duration_value = int(reps_raw) if reps_raw else 10
                elif reps_range:
                    # reps_range specified (e.g., "6-8") - parse upper bound for FIT
                    duration_type = "reps"
                    try:
                        # Parse upper bound from range like "6-8" -> 8
                        parts = reps_range.replace('-', ' ').split()
                        duration_value = int(parts[-1]) if parts else 10
                    except:
                        duration_value = 10
                else:
                    # No reps, no distance, no time - use lap button
                    # This is standard for cardio/running exercises like "Indoor Track Run"
                    duration_type = "lap_button"
                    duration_value = 0

            start_index = len(steps)

            # Exercise step
            # Include exercise_name_id (real FIT SDK ID) if available from lookup
            step = {
                'type': 'exercise',
                'display_name': display_name,
                'original_name': name,
                'category_id': category_id,
                'category_name': match['category_name'],
                'intensity': 'active',
                'duration_type': duration_type,
                'duration_value': duration_value,
                'reps': reps_raw,
                'sets': sets,
            }
            # Add real FIT SDK exercise_name_id if available (e.g., 37 for GOBLET_SQUAT)
            if match.get('exercise_name_id') is not None:
                step['exercise_name_id'] = match['exercise_name_id']
            steps.append(step)

            # Rest step between sets (if sets > 1)
            if sets > 1 and rest_between_sets > 0:
                steps.append(_create_rest_step(rest_between_sets, rest_type_block))

            # Repeat step (if sets > 1)
            if sets > 1:
                steps.append({
                    'type': 'repeat',
                    'duration_step': start_index,
                    'repeat_count': sets - 1,
                })

            # Check if this is the last exercise overall in the block
            is_last_exercise = (all_exercises.index(exercise) == len(all_exercises) - 1)

            # Rest after exercise (if rest_sec is set on the exercise)
            exercise_rest = exercise.get('rest_sec')
            exercise_rest_type = exercise.get('rest_type', 'timed')
            if exercise_rest and exercise_rest > 0:
                # Don't add rest after the very last exercise in the workout
                if not (is_last_block and is_last_exercise):
                    steps.append(_create_rest_step(exercise_rest, exercise_rest_type))

            # Rest after superset (if this is the last exercise in a superset)
            if exercise.get('_is_last_in_superset') and exercise.get('_superset_rest'):
                superset_rest = exercise.get('_superset_rest')
                superset_rest_type = exercise.get('_superset_rest_type', 'timed')
                # Don't add rest after the very last superset in the workout
                if not (is_last_block and exercise.get('_is_last_superset')):
                    steps.append(_create_rest_step(superset_rest, superset_rest_type))

        # Rest after block (if rest_between_rounds_sec is set)
        if rest_after_block and rest_after_block > 0 and not is_last_block:
            steps.append(_create_rest_step(rest_after_block, rest_type_block))

    return steps, category_ids_used


def detect_sport_type(category_ids: Set[int]) -> Tuple[int, int, str, List[str]]:
    """
    Detect optimal Garmin sport type based on exercise categories used.

    Returns tuple of (sport_id, sub_sport_id, sport_name, warnings)

    Sport types (valid combinations for Garmin):
    - 1/0 = running/generic (for run-only workouts)
    - 10/26 = training/cardio_training (for workouts with ANY cardio)
    - 10/20 = training/strength_training (for strength-only workouts)

    NOTE: fitness_equipment (4) does NOT work on most Garmin watches!
    Always use training (10) for custom workouts.

    Priority: If workout has ANY cardio (run, row, ski) → cardio_training
    This is important for HYROX and similar mixed conditioning workouts.
    """
    RUNNING_CATEGORIES = {32}  # Run
    CARDIO_MACHINE_CATEGORIES = {2, 23}  # Cardio, Row

    has_running = bool(category_ids & RUNNING_CATEGORIES)
    has_cardio_machines = bool(category_ids & CARDIO_MACHINE_CATEGORIES)
    strength_categories = category_ids - RUNNING_CATEGORIES - CARDIO_MACHINE_CATEGORIES
    has_strength = bool(strength_categories)

    warnings = []

    # Determine best sport type
    # Priority: cardio takes precedence over strength for mixed workouts
    if has_running and not has_strength and not has_cardio_machines:
        # Pure running workout
        return 1, 0, "running", warnings

    if has_running or has_cardio_machines:
        # Any workout with cardio exercises (run, row, ski) -> cardio_training
        # This includes HYROX and other mixed conditioning workouts
        return 10, 26, "cardio", warnings

    if has_strength:
        # Pure strength workout (no cardio)
        return 10, 20, "strength", warnings

    # Default to strength training
    return 10, 20, "strength", warnings


def _duration_type_to_fit(duration_type: str) -> WorkoutStepDuration:
    """Convert our duration type string to FIT SDK enum."""
    mapping = {
        "time": WorkoutStepDuration.TIME,
        "distance": WorkoutStepDuration.DISTANCE,
        "reps": WorkoutStepDuration.REPS,
        "lap_button": WorkoutStepDuration.OPEN,  # OPEN = until lap button pressed
        "repeat": WorkoutStepDuration.REPEAT_UNTIL_STEPS_CMPLT,
    }
    return mapping.get(duration_type, WorkoutStepDuration.REPS)


def _sport_to_fit(sport_id: int) -> Sport:
    """Convert sport ID to FIT SDK Sport enum."""
    mapping = {
        1: Sport.RUNNING,
        10: Sport.TRAINING,
    }
    return mapping.get(sport_id, Sport.TRAINING)


def _sub_sport_to_fit(sub_sport_id: int) -> SubSport:
    """Convert sub sport ID to FIT SDK SubSport enum."""
    if sub_sport_id == 20:
        return SubSport.STRENGTH_TRAINING
    if sub_sport_id == 26:
        return SubSport.CARDIO_TRAINING
    return SubSport.GENERIC


def build_fit_workout(
    blocks_json: Dict[str, Any],
    force_sport_type: Optional[str] = None,
    use_lap_button: bool = False
) -> bytes:
    """
    Build a Garmin-compatible FIT workout file.

    Args:
        blocks_json: Workout data with blocks/exercises
        force_sport_type: Override auto-detection. Options: "strength", "cardio", "running"
        use_lap_button: If True, use lap button press for all exercises

    Returns:
        bytes: FIT file binary data
    """
    title = blocks_json.get('title', 'Workout')[:50]
    steps, category_ids = blocks_to_steps(blocks_json, use_lap_button=use_lap_button)

    if not steps:
        raise ValueError("No exercises found")

    # Auto-detect or use forced sport type
    # NOTE: fitness_equipment (4) does NOT work on Garmin watches!
    if force_sport_type == "strength":
        sport_id, sub_sport_id = 10, 20  # training/strength_training
    elif force_sport_type == "cardio":
        sport_id, sub_sport_id = 10, 26  # training/cardio_training
    elif force_sport_type == "running":
        sport_id, sub_sport_id = 1, 0    # running/generic
    else:
        sport_id, sub_sport_id, _, _ = detect_sport_type(category_ids)

    # ---- File ID Message ----
    file_id = FileIdMessage()
    file_id.type = FileType.WORKOUT
    file_id.manufacturer = Manufacturer.DEVELOPMENT.value
    file_id.product = 0
    file_id.time_created = round(datetime.now().timestamp() * 1000)
    file_id.serial_number = 0x12345678

    # ---- Workout Message ----
    workout_msg = WorkoutMessage()
    workout_msg.workoutName = title
    workout_msg.sport = _sport_to_fit(sport_id)
    # Count only exercise steps (not rest or repeat)
    workout_msg.num_valid_steps = len([s for s in steps if s['type'] != 'repeat'])

    # ---- Build FIT file ----
    builder = FitFileBuilder(auto_define=True, min_string_size=50)
    builder.add(file_id)
    builder.add(workout_msg)

    # Track exercise IDs per category
    # We prefer real FIT SDK exercise_name_id when available (e.g., 37 for GOBLET_SQUAT)
    # Fall back to sequential IDs for exercises without a known FIT SDK ID
    category_exercise_ids: Dict[Tuple[int, str], int] = {}
    exercise_name_counter: Dict[int, int] = {}  # category_id -> next_id for fallback

    def get_exercise_id(step: Dict[str, Any]) -> int:
        """Get exercise_name ID for a step.

        Uses real FIT SDK exercise_name_id when available (e.g., GOBLET_SQUAT=37).
        Falls back to sequential ID if no real ID is known.
        """
        category_id = step['category_id']
        display_name = step['display_name']
        key = (category_id, display_name)

        # First check if we already assigned an ID for this (category, name) pair
        if key in category_exercise_ids:
            return category_exercise_ids[key]

        # Use real FIT SDK ID if available
        if 'exercise_name_id' in step:
            category_exercise_ids[key] = step['exercise_name_id']
            return step['exercise_name_id']

        # Fallback: assign a sequential ID starting from 0
        # Note: Using 1000+ is invalid for FIT SDK exercise_name and causes Garmin watches to reject
        if category_id not in exercise_name_counter:
            exercise_name_counter[category_id] = 0
        category_exercise_ids[key] = exercise_name_counter[category_id]
        exercise_name_counter[category_id] += 1
        return category_exercise_ids[key]

    # First pass: collect all unique exercise IDs
    for step in steps:
        if step['type'] == 'exercise':
            get_exercise_id(step)

    # Add ExerciseTitleMessage for each unique (category_id, exercise_name) pair
    # This tells the watch what name to display for each exercise
    for (cat_id, display_name), exercise_name_id in category_exercise_ids.items():
        etm = ExerciseTitleMessage()
        etm.exercise_category = cat_id
        etm.exercise_name = exercise_name_id
        etm.workout_step_name = display_name[:50]
        builder.add(etm)

    # Add workout steps
    step_index = 0
    for step in steps:
        ws = WorkoutStepMessage()
        ws.message_index = step_index

        if step['type'] == 'exercise':
            ws.workout_step_name = step['display_name'][:50]
            ws.intensity = Intensity.ACTIVE
            ws.duration_type = _duration_type_to_fit(step['duration_type'])

            if step['duration_type'] == 'reps':
                ws.duration_reps = step['duration_value']
            elif step['duration_type'] == 'time':
                ws.duration_time = step['duration_value'] / 1000.0  # ms to seconds
            elif step['duration_type'] == 'distance':
                ws.duration_distance = step['duration_value'] / 100.0  # cm to meters
            elif step['duration_type'] == 'lap_button':
                ws.duration_type = WorkoutStepDuration.OPEN

            ws.target_type = WorkoutStepTarget.OPEN
            ws.exercise_category = step['category_id']
            ws.exercise_name = get_exercise_id(step)

        elif step['type'] == 'rest':
            ws.workout_step_name = "Rest"
            ws.intensity = Intensity.REST
            ws.duration_type = WorkoutStepDuration.TIME
            ws.duration_time = step['duration_value'] / 1000.0
            ws.target_type = WorkoutStepTarget.OPEN

        elif step['type'] == 'repeat':
            ws.duration_type = WorkoutStepDuration.REPEAT_UNTIL_STEPS_CMPLT
            ws.duration_step = step['duration_step']
            ws.target_value = step['repeat_count']
            step_index += 1
            builder.add(ws)
            continue  # Don't increment for repeats

        builder.add(ws)
        step_index += 1

    # Build and write to temp file
    fit_file = builder.build()

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".fit") as tmp:
            tmp_path = tmp.name

        fit_file.to_file(tmp_path)

        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass


def get_fit_metadata(
    blocks_json: Dict[str, Any],
    use_lap_button: bool = False
) -> Dict[str, Any]:
    """
    Analyze workout and return metadata about FIT export.

    Args:
        blocks_json: Workout data with blocks/exercises
        use_lap_button: If True, indicates lap button mode will be used

    Returns dict with:
        - detected_sport: The auto-detected sport type
        - detected_sport_id: FIT sport ID
        - warnings: List of warnings about the export
        - exercise_count: Total number of exercises
        - has_running: Whether workout contains running exercises
        - has_cardio: Whether workout contains cardio machine exercises
        - has_strength: Whether workout contains strength exercises
        - use_lap_button: Whether lap button mode is enabled
        - steps: List of step previews for UI
    """
    steps, category_ids = blocks_to_steps(blocks_json, use_lap_button=use_lap_button)
    sport_id, sub_sport_id, sport_name, warnings = detect_sport_type(category_ids)

    RUNNING_CATEGORIES = {32}
    CARDIO_MACHINE_CATEGORIES = {2, 23}

    has_running = bool(category_ids & RUNNING_CATEGORIES)
    has_cardio = bool(category_ids & CARDIO_MACHINE_CATEGORIES)
    strength_cats = category_ids - RUNNING_CATEGORIES - CARDIO_MACHINE_CATEGORIES
    has_strength = bool(strength_cats)

    return {
        "detected_sport": sport_name,
        "detected_sport_id": sport_id,
        "detected_sub_sport_id": sub_sport_id,
        "warnings": warnings,
        "exercise_count": len([s for s in steps if s['type'] == 'exercise']),
        "has_running": has_running,
        "has_cardio": has_cardio,
        "has_strength": has_strength,
        "category_ids": list(category_ids),
        "use_lap_button": use_lap_button,
        "steps": steps,  # Include steps for preview
    }
