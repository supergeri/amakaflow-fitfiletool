"""
Preview Module

Generates preview data for the UI that exactly matches what will be exported to FIT.
This ensures the preview and export are always in sync.
"""

from typing import Dict, Any, List

from .fit_builder import blocks_to_steps, detect_sport_type


def get_preview_steps(
    blocks_json: Dict[str, Any],
    use_lap_button: bool = False
) -> List[Dict[str, Any]]:
    """
    Get preview steps that match exactly what will be exported to FIT.

    This is the single source of truth for exercise preview.
    The UI should call this endpoint instead of doing local mapping.

    Args:
        blocks_json: Workout data with blocks/exercises
        use_lap_button: If True, show lap button mode in preview

    Returns:
        List of step dictionaries with:
        - type: 'exercise', 'rest', 'repeat', or 'warmup'
        - display_name: Name shown on watch
        - original_name: Original exercise name from input
        - category_id: FIT SDK category ID
        - category_name: Category display name
        - duration_type: 'reps', 'time', 'distance', 'open', or 'lap_button'
        - duration_value: The value (reps count, ms, cm)
        - duration_display: Human-readable duration string (e.g., "Press Lap", "30s")
        - sets: Number of sets (if > 1)
        - rest_seconds: Rest duration (for rest steps)
        - is_rest: Boolean flag for rest steps (AMA-95)
        - step_type: 'active', 'rest', 'warmup', 'cooldown' for styling (AMA-95)
    """
    steps, category_ids = blocks_to_steps(blocks_json, use_lap_button=use_lap_button)

    preview_steps = []
    for step in steps:
        preview_step = {
            "type": step["type"],
            "display_name": step.get("display_name", ""),
        }

        if step["type"] == "exercise":
            preview_step.update({
                "original_name": step.get("original_name", ""),
                "category_id": step.get("category_id"),
                "category_name": step.get("category_name", ""),
                "duration_type": step.get("duration_type"),
                "reps": step.get("reps"),
                "sets": step.get("sets", 1),
                "intensity": step.get("intensity", "active"),
                "is_warmup_set": step.get("is_warmup_set", False),  # AMA-94: Flag for warm-up sets
                "is_rest": False,  # AMA-95: Explicit rest flag for preview
                "step_type": "active",  # AMA-95: Step type for display styling
            })

            # Create human-readable duration display
            dtype = step.get("duration_type")
            dvalue = step.get("duration_value", 0)

            if dtype == "lap_button":
                preview_step["duration_display"] = "Lap Button"
            elif dtype == "reps":
                preview_step["duration_display"] = f"{dvalue} reps"
            elif dtype == "time":
                seconds = dvalue / 1000
                if seconds >= 60:
                    mins = int(seconds // 60)
                    secs = int(seconds % 60)
                    preview_step["duration_display"] = f"{mins}:{secs:02d}"
                else:
                    preview_step["duration_display"] = f"{int(seconds)}s"
            elif dtype == "distance":
                meters = dvalue / 100
                if meters >= 1000:
                    preview_step["duration_display"] = f"{meters/1000:.1f}km"
                else:
                    preview_step["duration_display"] = f"{int(meters)}m"
            else:
                preview_step["duration_display"] = str(step.get("reps", ""))

        elif step["type"] == "rest":
            rest_sec = step.get("rest_seconds", step.get("duration_value", 0) / 1000)
            preview_step["rest_seconds"] = rest_sec
            preview_step["is_rest"] = True  # AMA-95: Explicit rest flag
            preview_step["step_type"] = "rest"  # AMA-95: Step type for display styling
            preview_step["duration_type"] = step.get("duration_type", "open")
            # Check if it's a button-press rest (lap_button or open duration type)
            if step.get("duration_type") in ("lap_button", "open") or rest_sec <= 0:
                preview_step["duration_display"] = "Press Lap"
            else:
                preview_step["duration_display"] = f"{int(rest_sec)}s"

        elif step["type"] == "repeat":
            preview_step["repeat_count"] = step.get("repeat_count", 0)
            preview_step["duration_step"] = step.get("duration_step", 0)

        elif step["type"] == "warmup":
            preview_step.update({
                "category_id": step.get("category_id"),
                "category_name": step.get("category_name", "Cardio"),
                "is_rest": False,  # AMA-95: Not a rest step
                "step_type": "warmup",  # AMA-95: Step type for display styling
            })
            # Warmup duration handling
            dtype = step.get("duration_type")
            duration_value = step.get("duration_value", 0)
            if dtype == 5:  # OPEN (lap button)
                preview_step["duration_display"] = "Press Lap"
                preview_step["duration_type"] = "open"
            elif dtype == 0 and duration_value > 0:  # TIME (milliseconds)
                # Convert ms to human-readable format
                total_sec = duration_value // 1000
                if total_sec >= 60:
                    minutes = total_sec // 60
                    secs = total_sec % 60
                    if secs > 0:
                        preview_step["duration_display"] = f"{minutes}m {secs}s"
                    else:
                        preview_step["duration_display"] = f"{minutes}m"
                else:
                    preview_step["duration_display"] = f"{total_sec}s"
                preview_step["duration_type"] = "time"
            else:
                preview_step["duration_display"] = "Press Lap"
                preview_step["duration_type"] = "open"

        preview_steps.append(preview_step)

    return preview_steps


def get_preview_summary(
    blocks_json: Dict[str, Any],
    use_lap_button: bool = False
) -> Dict[str, Any]:
    """
    Get a summary of the workout for preview display.

    Returns:
        Dictionary with:
        - title: Workout title
        - sport_type: Detected sport type name
        - exercise_count: Total exercises
        - rest_count: Total rest steps (AMA-95)
        - total_sets: Total sets across all exercises
        - has_running: Boolean
        - has_cardio: Boolean
        - has_strength: Boolean
        - warnings: List of warnings
        - steps: Full step list for detailed preview
    """
    steps, category_ids = blocks_to_steps(blocks_json, use_lap_button=use_lap_button)
    sport_id, sub_sport_id, sport_name, warnings = detect_sport_type(category_ids)

    preview_steps = get_preview_steps(blocks_json, use_lap_button=use_lap_button)

    # Count exercises, sets, and rest steps (AMA-95)
    exercise_steps = [s for s in steps if s["type"] == "exercise"]
    rest_steps = [s for s in steps if s["type"] == "rest"]
    exercise_count = len(exercise_steps)
    rest_count = len(rest_steps)
    total_sets = sum(s.get("sets", 1) for s in exercise_steps)

    RUNNING_CATEGORIES = {32}
    CARDIO_MACHINE_CATEGORIES = {2, 23}

    has_running = bool(category_ids & RUNNING_CATEGORIES)
    has_cardio = bool(category_ids & CARDIO_MACHINE_CATEGORIES)
    strength_cats = category_ids - RUNNING_CATEGORIES - CARDIO_MACHINE_CATEGORIES
    has_strength = bool(strength_cats)

    return {
        "title": blocks_json.get("title", "Workout"),
        "sport_type": sport_name,
        "sport_id": sport_id,
        "exercise_count": exercise_count,
        "rest_count": rest_count,  # AMA-95: Count of rest steps
        "total_sets": total_sets,
        "has_running": has_running,
        "has_cardio": has_cardio,
        "has_strength": has_strength,
        "warnings": warnings,
        "use_lap_button": use_lap_button,
        "steps": preview_steps,
    }
