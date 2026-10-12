"""Deterministic TutorAction validator and repairer (§23).

Validates a proposed TutorAction against the ontology and current state,
repairs fixable issues, and returns a clean action.
"""

from __future__ import annotations

from typing import Any

from app.math.schemas import MathEvaluation
from app.pedagogy.schemas import (
    ActionTarget,
    StudentState,
    TutorAction,
)

# Canonical valid target types
_VALID_TARGET_TYPES = frozenset(
    {
        "current_claim",
        "error",
        "misconception",
        "statement",
        "subgoal",
        "method",
        "representation",
        "prerequisite",
        "student_question",
        "whole_problem",
    }
)

# Moves that are inherently question-like and require a response demand
_QUESTION_MOVES: frozenset[str] = frozenset(
    {
        "ASK_NEXT_STEP",
        "ASK_EXPLANATION",
        "ASK_JUSTIFICATION",
        "ASK_PREDICTION",
        "ASK_COMPARE_METHODS",
        "ASK_CHECK_WORK",
        "PUMP",
        "PROMPT",
        "PROMPT_SELF_CORRECTION",
    }
)


def validate_action(
    action: TutorAction,
    state: StudentState,
    math_evaluations: list[MathEvaluation],
    ontology: dict[str, Any],
) -> tuple[bool, TutorAction, list[str]]:
    """Validate a TutorAction and repair if possible (§23).

    Returns
    -------
    is_valid : bool
        Whether the original action passed all checks (before any repair).
    repaired_action : TutorAction
        The action after any needed repairs.  Equals the original when valid.
    issues : list[str]
        Human-readable descriptions of every issue found.
    """

    issues: list[str] = []
    mode = action.mode
    move = action.move
    help_level = action.help_level
    feedback = action.feedback
    expected_response = action.expected_response
    target = action.target

    mode_move_compat: dict[str, list[str]] = ontology.get("mode_move_compatibility", {})
    move_help_compat: dict[str, list[int]] = ontology.get("move_help_compatibility", {})
    response_demand: dict[str, str] = ontology.get("response_demand", {})

    # ── Check 1: Legal mode/move pair ────────────────────────────────
    allowed_moves = mode_move_compat.get(mode, [])
    if move not in allowed_moves:
        issues.append(f"Move {move} is not allowed in mode {mode}. Allowed: {allowed_moves}.")
        if allowed_moves:
            move = allowed_moves[0]
        else:
            mode = "ELICIT"
            move = "ASK_NEXT_STEP"

    # ── Check 2: Legal move/help pair ────────────────────────────────
    allowed_help = move_help_compat.get(move, [0])
    if help_level not in allowed_help:
        issues.append(
            f"Help level {help_level} is not allowed for move {move}. Allowed: {allowed_help}."
        )
        help_level = min(allowed_help, key=lambda h: abs(h - help_level))  # type: ignore[assignment]

    # ── Check 3: No positive feedback on false/contradicted math ─────
    has_error = any(
        ev.truth == "false" or ev.grounding == "contradicted" for ev in math_evaluations
    )
    if feedback == "POSITIVE" and has_error:
        issues.append("Positive feedback given on false/contradicted math. Changing to CORRECTIVE.")
        feedback = "CORRECTIVE"

    # ── Check 4: No corrective feedback on fully verified progressing ─
    all_progressing = math_evaluations and all(
        ev.truth == "true" and ev.progress in ("progressing", "goal_achieved")
        for ev in math_evaluations
    )
    if feedback == "CORRECTIVE" and all_progressing:
        issues.append(
            "Corrective feedback given on fully verified progressing claim. Changing to POSITIVE."
        )
        feedback = "POSITIVE"

    # ── Check 5: Target type is valid ────────────────────────────────
    if target.type not in _VALID_TARGET_TYPES:
        issues.append(f"Invalid target type '{target.type}'. Defaulting to 'whole_problem'.")
        target = ActionTarget(type="whole_problem")

    # ── Check 6: H >= 4 should have verified math payload potential ──
    if help_level >= 4:
        # We can't check the actual MathPayload here (it's built downstream),
        # but we can flag if there are no evaluations to ground it
        if not math_evaluations and move in (
            "WORKED_MICROSTEP",
            "CORRECT_EXPLICITLY",
            "EXPLAIN_CONCEPT",
            "EXPLAIN_ERROR",
        ):
            issues.append(
                f"Help level {help_level} with move {move} but no math "
                "evaluations to ground a verified payload."
            )

    # ── Check 7: Question-like moves need non-NONE response demand ───
    if move in _QUESTION_MOVES and expected_response == "NONE":
        canonical_demand = response_demand.get(move, "CONTINUE")
        issues.append(
            f"Question move {move} has NONE response demand. Setting to {canonical_demand}."
        )
        expected_response = canonical_demand  # type: ignore[assignment]

    # ── Check 8: CLOSE only when closure conditions met ──────────────
    if mode == "CLOSE" and not state.goal_completed:
        issues.append(
            "CLOSE mode selected but goal_completed is False. Falling back to ELICIT/ASK_NEXT_STEP."
        )
        mode = "ELICIT"
        move = "ASK_NEXT_STEP"
        help_level = 0
        # Re-derive help level validity
        allowed_help = move_help_compat.get(move, [0])
        if help_level not in allowed_help:
            help_level = allowed_help[0]

    # ── Build repaired action ────────────────────────────────────────
    is_valid = len(issues) == 0

    repaired = TutorAction(
        mode=mode,
        move=move,
        help_level=help_level,
        feedback=feedback,
        expected_response=expected_response,
        target=target,
    )

    return is_valid, repaired, issues
