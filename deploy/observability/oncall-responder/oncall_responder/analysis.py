"""A model's answer, checked before any of it can reach a report.

The answer is untrusted text. It must be one JSON object with exactly the schema's keys, every
string plain, short and free of secrets, and it must pass a content policy: no URLs, no shell
or deploy or repository commands, nothing that disables alerts or asks for secrets, no echo of
injected instructions, and no root cause stated as fact. Evidence ids it cites must be ones the
responder actually collected. One violation rejects the whole answer, and the report is written
from `fallback()` instead: nothing a hostile or confused model writes gets through partially.
"""

import json
import re
from dataclasses import dataclass

from oncall_responder.evidence import Evidence
from oncall_responder.incident import Incident
from oncall_responder.privacy import fold, mixed_script, plain, scrub

MAX_RAW = 16 * 1024
ASSESSMENT = 600
ITEM = 240
MAX_CAUSES, MAX_ACTIONS, MAX_STEPS, MAX_LIMITATIONS, MAX_CITED = 4, 5, 4, 5, 4
CONFIDENCE = ("low", "medium", "high")
RANK = {"low": 0, "medium": 1, "high": 2}
CERTAINTY = ("possible", "probable")
ACTION_KINDS = ("investigate", "verify", "monitor", "escalate", "human_change")
FIELDS = frozenset(
    {
        "assessment",
        "likely_causes",
        "recommended_actions",
        "verification_steps",
        "confidence",
        "escalation_required",
        "limitations",
    }
)
INCIDENT_ID = "incident"  # the incident itself, always citable

# Things a report must never contain. Each pattern is a code in a rejection, not a value.
POLICY: dict[str, re.Pattern] = {
    "url": re.compile(r"(?i)\b(?:[a-z][a-z0-9+.-]*://|www\.|data:[a-z]+/|javascript:)"),
    "shell": re.compile(r"`|\$\(|\$\{|&&|\|\||\|\s*(?:ba|z)?sh\b|>\s*/"),
    "command": re.compile(
        r"(?i)\b(?:sudo|su\s+-|curl|wget|nc|ncat|ssh|scp|rsync|chmod|chown|mkfs|systemctl|"
        r"docker|podman|kubectl|helm|terraform|ansible|aws|gcloud|az|gh|psql|mysql|python|bash|"
        r"powershell|eval|exec|rm\s+-)\b"
    ),
    "repository": re.compile(
        r"(?i)\bgit\s+(?:push|commit|merge|rebase|reset|checkout|tag)\b"
        r"|\b(?:push|commit|merge|force-push|open a pull request|approve the pull request)\b"
    ),
    "deploy": re.compile(
        r"(?i)\b(?:deploy(?:ing|ment|ed)?|redeploy|promote|promotion|roll\s?back|"
        r"restart the (?:service|server|container|database))\b"
    ),
    "database-write": re.compile(
        r"(?i)\b(?:drop\s+table|delete\s+from|truncate|insert\s+into|update\s+\w+\s+set|alter\s+table)\b"
    ),
    "alerting-change": re.compile(
        r"(?i)\b(?:disable|delete|remove|silence|mute|pause|turn off|suppress|snooze|"
        r"lower the threshold|raise the threshold|ignore the alert)\b[^.]{0,60}"
        r"\b(?:alert|alerts|alerting|rule|rules|notification|notifications|monitor|monitoring|"
        r"paging)\b"
    ),
    "secrets": re.compile(
        r"(?i)\b(?:reveal|print|dump|show|send|share|expose|leak|exfiltrate|email|post|read|cat)\b"
        r"[^.]{0,60}(?:\b(?:secret|secrets|password|passwords|token|tokens|credential|credentials|"
        r"api key|cookie|cookies|env|environment variables?)\b|\.env\b)"
    ),
    "injection-echo": re.compile(
        r"(?i)ignore (?:all |any |the )?(?:previous|prior|above)|disregard (?:all |any |the )?"
        r"(?:previous|prior|above)|system prompt|you are now|new instructions|jailbreak"
    ),
    "unproven-cause": re.compile(
        r"(?i)\broot cause (?:is|was)\b"
        r"|\b(?:is|was|are|were) (?:definitely |certainly |clearly )?caused by\b"
        r"|\bproves?\b|\bconfirmed (?:that|root|cause)\b|\bundoubtedly\b|\bwithout doubt\b"
    ),
}


def confidence_ceiling(sources: set[str]) -> str:
    """The most confidence the evidence supports, from which backends found something.

    Nothing in Prometheus: low. Metrics alone: medium. High needs a second kind of evidence, logs
    or traces that also found something. A query that returned nothing counts for none of it.
    """
    if "prometheus" not in sources:
        return "low"
    return "high" if sources & {"loki", "tempo"} else "medium"


class AnalysisRejected(Exception):
    """The model's answer was refused; `code` says which rule, never what the answer said."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Analysis:
    assessment: str
    causes: tuple[dict, ...]
    actions: tuple[dict, ...]
    steps: tuple[str, ...]
    confidence: str
    escalation_required: bool
    limitations: tuple[str, ...]


def check_text(value: object, limit: int, where: str, secrets: tuple[str, ...]) -> str:
    """`value` if it is plain, bounded, secret-free text that passes the policy; else reject."""
    if not isinstance(value, str) or not value.strip():
        raise AnalysisRejected(f"{where}-not-text")
    if len(value) > limit:
        raise AnalysisRejected(f"{where}-too-long")
    if plain(value, limit) != value:  # markup, control and invisible format characters
        raise AnalysisRejected(f"{where}-not-plain")
    if mixed_script(value):  # a word that mixes alphabets is how look-alike letters hide a command
        raise AnalysisRejected(f"{where}-mixed-script")
    # The policy reads the text as written and as it would look in plain ASCII (fullwidth letters,
    # accents and look-alike letters folded), so "ｃｕｒｌ" is no safer than "curl".
    folded = fold(value)
    if scrub(value, secrets) != value or scrub(folded, secrets) != folded:
        raise AnalysisRejected(f"{where}-secret-or-personal-data")
    for code, pattern in POLICY.items():
        if pattern.search(value) or pattern.search(folded):
            raise AnalysisRejected(f"{where}-{code}")
    return value


def items(data: dict, key: str, limit: int) -> list:
    value = data[key]
    if not isinstance(value, list) or len(value) > limit:
        raise AnalysisRejected(f"{key}-malformed")
    return value


def exact(item: object, keys: set[str], where: str) -> dict:
    if not isinstance(item, dict) or set(item) != keys:
        raise AnalysisRejected(f"{where}-malformed")
    return item


def parse_analysis(raw: object, evidence: Evidence, secrets: tuple[str, ...] = ()) -> Analysis:
    """The model's answer as an Analysis, or AnalysisRejected."""
    if not isinstance(raw, str) or len(raw) > MAX_RAW:
        raise AnalysisRejected("answer-too-large")
    try:
        data = json.loads(raw)
    except ValueError:
        raise AnalysisRejected("answer-not-json") from None
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise AnalysisRejected("answer-fields")
    citable = evidence.grounded | {INCIDENT_ID}

    causes = []
    for entry in items(data, "likely_causes", MAX_CAUSES):
        entry = exact(entry, {"cause", "certainty", "evidence_ids"}, "cause")
        cited = entry["evidence_ids"]
        if not isinstance(cited, list) or not 1 <= len(cited) <= MAX_CITED:
            raise AnalysisRejected("cause-evidence-missing")
        unsupported = [i for i in cited if not isinstance(i, str) or i not in citable]
        if unsupported:
            # Evidence that found nothing is told apart from evidence that isn't there at all.
            silent = all(isinstance(i, str) and i in evidence.silent for i in unsupported)
            raise AnalysisRejected(
                "cause-cites-empty-evidence" if silent else "cause-cites-unknown-evidence"
            )
        if entry["certainty"] not in CERTAINTY:
            raise AnalysisRejected("cause-certainty")
        causes.append(
            {
                "cause": check_text(entry["cause"], ITEM, "cause", secrets),
                "certainty": entry["certainty"],
                "evidence_ids": list(dict.fromkeys(cited)),
            }
        )

    actions = []
    for entry in items(data, "recommended_actions", MAX_ACTIONS):
        entry = exact(entry, {"action", "kind"}, "action")
        if entry["kind"] not in ACTION_KINDS:
            raise AnalysisRejected("action-kind")
        actions.append(
            {"action": check_text(entry["action"], ITEM, "action", secrets), "kind": entry["kind"]}
        )

    steps = [
        check_text(s, ITEM, "step", secrets) for s in items(data, "verification_steps", MAX_STEPS)
    ]
    limitations = [
        check_text(s, ITEM, "limitation", secrets)
        for s in items(data, "limitations", MAX_LIMITATIONS)
    ]
    if data["confidence"] not in CONFIDENCE:
        raise AnalysisRejected("confidence")
    if not isinstance(data["escalation_required"], bool):
        raise AnalysisRejected("escalation-not-boolean")
    # Confidence can't outrun what was observed (confidence_ceiling).
    ceiling = confidence_ceiling(evidence.sources)
    if RANK[data["confidence"]] > RANK[ceiling]:
        raise AnalysisRejected(
            "confidence-without-evidence" if ceiling == "low" else "confidence-above-evidence"
        )
    return Analysis(
        assessment=check_text(data["assessment"], ASSESSMENT, "assessment", secrets),
        causes=tuple(causes),
        actions=tuple(actions),
        steps=tuple(steps),
        confidence=data["confidence"],
        escalation_required=data["escalation_required"],
        limitations=tuple(limitations),
    )


def fallback(incident: Incident, evidence: Evidence, reason: str) -> Analysis:
    """The report when the model can't be used: fixed text, no inference, a human decides."""
    where = incident.environment or "an unknown environment"
    return Analysis(
        assessment=(
            f"The automated analysis was not used ({reason}). The alert is {incident.status} in "
            f"{where}; the evidence below was collected by fixed queries, and no cause is proposed."
        ),
        causes=(),
        actions=(
            {
                "action": (
                    "Open the dashboard panel linked from the incident and compare the value with "
                    "the threshold."
                ),
                "kind": "investigate",
            },
            {
                "action": (
                    "Read the evidence below, then check the application logs and traces for the "
                    "same period."
                ),
                "kind": "investigate",
            },
        ),
        steps=("The alert returns to Normal in Grafana.",),
        confidence="low",
        escalation_required=incident.severity == "critical" and incident.status == "firing",
        limitations=(f"The model's answer was not used: {reason}.",),
    )
