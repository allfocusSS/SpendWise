"""One incident in, one report out: evidence, prompt, model, validation, report."""

import time
from collections.abc import Callable

from oncall_responder.analysis import Analysis, AnalysisRejected, fallback, parse_analysis
from oncall_responder.evidence import Backends, Evidence, collect
from oncall_responder.incident import Incident
from oncall_responder.model import Model
from oncall_responder.prompt import build_messages
from oncall_responder.report import build_report, validate_report


class ReportInvalid(Exception):
    """Even the fallback report failed validation; nothing is stored."""


def respond(
    incident: Incident,
    backends: Backends,
    model: Model,
    secrets: tuple[str, ...] = (),
    audit: Callable[[str], None] = lambda line: None,
    now: Callable[[], float] = time.time,
) -> dict:
    """The validated report for `incident`. A failing backend or model never stops it."""
    evidence = collect(incident, backends, secrets, audit)
    analysis, answer = ask(incident, evidence, model, secrets, audit)
    report = build_report(incident, evidence, analysis, model, answer, now())
    problems = validate_report(report, secrets)
    if problems:
        # The model's words were fine one by one but not as a report: write it without them.
        audit(f"report: invalid ({', '.join(sorted(set(problems)))}); using the fallback")
        analysis = fallback(incident, evidence, "report-invalid")
        report = build_report(
            incident, evidence, analysis, model, "rejected: report-invalid", now()
        )
        problems = validate_report(report, secrets)
        if problems:
            raise ReportInvalid(", ".join(sorted(set(problems))))
    return report


def ask(
    incident: Incident,
    evidence: Evidence,
    model: Model,
    secrets: tuple[str, ...],
    audit: Callable[[str], None],
) -> tuple[Analysis, str]:
    system, user = build_messages(incident, evidence)
    audit(f"model: {model.provider} invoked (prompt {len(system) + len(user)} characters)")
    try:
        analysis = parse_analysis(model.complete(system, user), evidence, secrets)
    except AnalysisRejected as rejected:
        audit(f"model: answer rejected ({rejected.code})")
        return fallback(incident, evidence, rejected.code), f"rejected: {rejected.code}"
    except Exception as error:  # a real model can fail in any way; only the class is logged
        audit(f"model: failed ({type(error).__name__})")
        return fallback(incident, evidence, "model-error"), "failed: model-error"
    audit("model: answer accepted")
    return analysis, "accepted"
