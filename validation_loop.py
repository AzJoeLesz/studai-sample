"""Generate, audit, repair loop for tutor replies.

A reply that fails the audit is never sent. If all attempts fail we use the
fixed template for the action, and audit that too.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.math.schemas import MathEvaluation, MathIR, MathWorkingState
from app.pedagogy.schemas import MathPayload, StudentState, TutorAction
from app.responder.auditor import AuditResult, audit_response, audit_response_async
from app.responder.fallback_templates import action_aware_fallback

logger = logging.getLogger(__name__)

# first try + 2 repairs
DEFAULT_MAX_ATTEMPTS = 3

GenerateFn = Callable[..., Awaitable[str]]
AuditFn = Callable[..., AuditResult]


@dataclass
class ValidationLoopResult:
    response_text: str
    audit_passed: bool
    attempts: int = 0
    used_fallback: bool = False
    final_audit: AuditResult | None = None
    attempt_issues: list[list[str]] = field(default_factory=list)
    audit_failed: bool = False


async def run_validation_loop(
    *,
    generate_fn: GenerateFn,
    problem_text: str,
    student_text: str,
    action: TutorAction,
    student_state: StudentState,
    math_evaluations: list[MathEvaluation] | None,
    math_payload: MathPayload | None,
    math_ir: MathIR | dict | None,
    locale: str,
    working_state: MathWorkingState | None = None,
    ontology: dict[str, Any] | None = None,
    audit_fn: AuditFn | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    use_async_audit: bool = True,
) -> ValidationLoopResult:
    """Never returns a candidate that failed audit. If the fallback fails
    too, returns the fixed "can't answer safely" message."""
    attempts = max(1, int(max_attempts))
    last_issues: list[str] = []
    attempt_issues: list[list[str]] = []
    repair_notes: list[str] = []

    for attempt in range(attempts):
        response_text = await generate_fn(
            problem_text=problem_text,
            student_text=student_text,
            action=action,
            student_state=student_state,
            math_evaluations=math_evaluations,
            math_payload=math_payload,
            math_ir=math_ir,
            locale=locale,
            repair_notes=repair_notes or None,
        )

        audit_result = await _run_audit(
            response_text,
            action,
            student_state,
            math_evaluations,
            math_payload,
            working_state,
            ontology,
            audit_fn=audit_fn,
            use_async_audit=use_async_audit,
        )

        if audit_result is None:
            # auditor down, fail closed
            logger.error(
                "response_audit_unavailable_fail_closed",
                extra={"attempt": attempt + 1},
            )
            attempt_issues.append(["auditor_unavailable"])
            break

        if audit_result.passed:
            return ValidationLoopResult(
                response_text=response_text,
                audit_passed=True,
                attempts=attempt + 1,
                used_fallback=False,
                final_audit=audit_result,
                attempt_issues=attempt_issues,
            )

        last_issues = list(audit_result.issues)
        attempt_issues.append(last_issues)
        repair_notes = last_issues
        logger.warning(
            "response_audit_failed",
            extra={"attempt": attempt + 1, "issues": last_issues},
        )

    # out of attempts: use the template, not the last candidate
    fallback = action_aware_fallback(action)
    fallback_audit = await _run_audit(
        fallback,
        action,
        student_state,
        math_evaluations,
        math_payload,
        working_state,
        ontology,
        audit_fn=audit_fn,
        use_async_audit=False,  # no LLM audit for the template
    )

    if fallback_audit is not None and fallback_audit.passed:
        return ValidationLoopResult(
            response_text=fallback,
            audit_passed=True,
            attempts=len(attempt_issues),
            used_fallback=True,
            final_audit=fallback_audit,
            attempt_issues=attempt_issues,
        )

    # last resort, no math in it
    ultra = "Most nem tudok biztonságosan válaszolni. Kérlek, próbáld meg később."
    logger.error(
        "audit_fallback_failed_using_ultra_safe",
        extra={
            "fallback_issues": (fallback_audit.issues if fallback_audit else ["no_audit"]),
            "prior_issues": last_issues,
        },
    )
    return ValidationLoopResult(
        response_text=ultra,
        audit_passed=False,
        attempts=len(attempt_issues),
        used_fallback=True,
        final_audit=fallback_audit,
        attempt_issues=attempt_issues,
        audit_failed=True,
    )


async def _run_audit(
    response_text: str,
    action: TutorAction,
    student_state: StudentState,
    evaluations: list[MathEvaluation] | None,
    math_payload: MathPayload | None,
    working_state: MathWorkingState | None,
    ontology: dict[str, Any] | None,
    *,
    audit_fn: AuditFn | None,
    use_async_audit: bool,
) -> AuditResult | None:
    try:
        if audit_fn is not None:
            return audit_fn(
                response_text,
                action,
                student_state,
                evaluations,
                math_payload=math_payload,
                working_state=working_state,
                ontology=ontology,
            )
        if use_async_audit:
            return await audit_response_async(
                response_text,
                action,
                student_state,
                evaluations,
                math_payload=math_payload,
                working_state=working_state,
                ontology=ontology,
            )
        return audit_response(
            response_text,
            action,
            student_state,
            evaluations,
            math_payload=math_payload,
            working_state=working_state,
            ontology=ontology,
        )
    except TypeError:
        # older audit_fn stubs don't take ontology
        try:
            if audit_fn is not None:
                return audit_fn(
                    response_text,
                    action,
                    student_state,
                    evaluations,
                    math_payload=math_payload,
                    working_state=working_state,
                )
        except Exception:
            logger.exception("auditor_error_fail_closed")
            return None
        return None
    except Exception:
        logger.exception("auditor_error_fail_closed")
        return None
