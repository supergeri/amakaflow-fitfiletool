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


def parse_structure(structure_str: Optional[str]) -> int:
    """Parse structure string like '3 rounds' to get count."""
    if not structure_str:
        return 1
    match = re.search(r'(\d+)', structure_str)
    return int(match.group(1)) if match else 1


def blocks_to_steps(
    blocks_json: Dict[str, Any],
    use_lap_button: bool = False
) -> Tuple[List[Dict[str, Any]], Set[int]]:
    """
    Convert blocks JSON to FIT workout steps.

    Args:
        blocks_json: Workout data with blocks/exercises
        use_lap_button: If True, use "lap button press" for all exercises

    Returns:
        Tuple of (steps list, set of category IDs used)
    """
    lookup = get_lookup()
    steps = []
    category_ids_used: Set[int] = set()

    for block in blocks_json.get('blocks', []):
        rounds = parse_structure(block.get('structure'))
        rest_between = block.get('rest_between_sec', 30) or 30

        all_exercises = []
        for superset in block.get('supersets', []):
            for exercise in superset.get('exercises', []):
                all_exercises.append(exercise)
        for exercise in block.get('exercises', []):
            all_exercises.append(exercise)

        for exercise in all_exercises:
            name = exercise.get('name', 'Exercise')
            reps_raw = exercise.get('reps') or 10
            sets = exercise.get('sets') or rounds
            duration_sec = exercise.get('duration_sec')
            distance_m = exercise.get('distance_m')  # Numeric distance in meters from ingestor

            match = lookup.find(name)
            raw_category_id = match['category_id']
            # Validate category ID - remap invalid (33+) to valid (0-32)
            category_id = validate_category_id(raw_category_id, name)
            category_ids_used.add(category_id)
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
                else:
                    duration_type = "reps"
                    if isinstance(reps_raw, str):
                        try:
                            duration_value = int(reps_raw.split('-')[0])
                        except:
                            duration_value = 10
                    else:
                        duration_value = int(reps_raw) if reps_raw else 10

            start_index = len(steps)

            # Exercise step
            steps.append({
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
            })

            # Rest step (if sets > 1)
            if sets > 1 and rest_between > 0:
                steps.append({
                    'type': 'rest',
                    'display_name': 'Rest',
                    'intensity': 'rest',
                    'duration_type': 'time',
                    'duration_value': int(rest_between * 1000),
                    'rest_seconds': rest_between,
                })

            # Repeat step (if sets > 1)
            if sets > 1:
                steps.append({
                    'type': 'repeat',
                    'duration_step': start_index,
                    'repeat_count': sets - 1,
                })

    return steps, category_ids_used


def detect_sport_type(category_ids: Set[int]) -> Tuple[int, int, str, List[str]]:
    """
    Detect optimal Garmin sport type based on exercise categories used.

    Returns tuple of (sport_id, sub_sport_id, sport_name, warnings)

    Sport types:
    - 1 = running (for run-only workouts)
    - 4 = fitness_equipment (for mixed cardio/strength, rowing, skiing)
    - 10 = training (for pure strength)
    """
    RUNNING_CATEGORIES = {32}  # Run
    CARDIO_MACHINE_CATEGORIES = {2, 23}  # Cardio, Row

    has_running = bool(category_ids & RUNNING_CATEGORIES)
    has_cardio_machines = bool(category_ids & CARDIO_MACHINE_CATEGORIES)
    strength_categories = category_ids - RUNNING_CATEGORIES - CARDIO_MACHINE_CATEGORIES
    has_strength = bool(strength_categories)

    warnings = []

    # Determine best sport type
    if has_running and not has_strength and not has_cardio_machines:
        return 1, 0, "running", warnings

    if has_running or has_cardio_machines:
        if has_strength:
            warnings.append(
                "This workout has both cardio (running/rowing/ski) and strength exercises. "
                "Exported as 'Cardio' type for best Garmin compatibility."
            )
        return 4, 0, "cardio", warnings

    # Pure strength workout
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
        4: Sport.FITNESS_EQUIPMENT,
        10: Sport.TRAINING,
    }
    return mapping.get(sport_id, Sport.TRAINING)


def _sub_sport_to_fit(sub_sport_id: int) -> SubSport:
    """Convert sub sport ID to FIT SDK SubSport enum."""
    if sub_sport_id == 20:
        return SubSport.STRENGTH_TRAINING
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
    if force_sport_type == "strength":
        sport_id, sub_sport_id = 10, 20
    elif force_sport_type == "cardio":
        sport_id, sub_sport_id = 4, 0
    elif force_sport_type == "running":
        sport_id, sub_sport_id = 1, 0
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
            ws.exercise_name = 0  # Default exercise within category

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
