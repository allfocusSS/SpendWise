"""What the responder accepts as an incident (oncall_responder/incident.py).

The alert receiver already normalized Grafana's webhook; the responder checks it again against
the exact `spendwise.incident.v1` contract, because it trusts nothing it is sent.
"""

import json

import pytest
from oncall_responder.incident import FIELDS, InvalidIncident, parse_incident
from oncall_support import GRAFANA, INJECTION, PATTERN_CANARIES, SECRET, incident_json


def parsed(**overrides):
    return parse_incident(incident_json(**overrides), GRAFANA)


def test_the_real_incident_is_accepted_with_every_field_checked() -> None:
    incident = parsed()
    assert (incident.status, incident.severity, incident.category) == ("firing", "warning", "ai")
    assert (incident.environment, incident.kind) == ("local", "condition")
    assert incident.fingerprint == "a7edbaa05b9b86b7"
    assert incident.value == 0.288079
    assert incident.dashboard_url.startswith(f"{GRAFANA}/d/spendwise-overview?")
    assert incident.panel_url.endswith("&viewPanel=19")


def test_the_model_sees_only_the_documented_fields() -> None:
    assert set(parsed().for_prompt()) == {
        "status",
        "alert",
        "kind",
        "severity",
        "category",
        "environment",
        "summary",
        "description",
        "runbook",
        "measured_value",
        "starts_at",
        "ends_at",
        "dashboard_url",
        "panel_url",
    }


def test_the_report_id_names_the_alert_its_state_and_its_start() -> None:
    firing = parsed()
    assert len(firing.report_id) == 16 and firing.report_id == parsed().report_id
    others = [
        parsed(status="resolved", ends_at="2026-11-15T16:21:20Z"),
        parsed(fingerprint="0123456789abcdef"),
        parsed(starts_at="2026-11-15T16:30:30Z"),
    ]
    assert len({firing.report_id, *(o.report_id for o in others)}) == 4


@pytest.mark.parametrize("field", sorted(FIELDS))
def test_a_missing_field_is_refused(field) -> None:
    data = incident_json()
    del data[field]
    with pytest.raises(InvalidIncident, match="fields differ from the contract"):
        parse_incident(data, GRAFANA)


@pytest.mark.parametrize("extra", ["labels", "annotations", "payload", "Status", "raw", ""])
def test_a_field_outside_the_contract_is_refused(extra) -> None:
    with pytest.raises(InvalidIncident, match="extra"):
        parse_incident(incident_json(**{extra: "x"}), GRAFANA)


@pytest.mark.parametrize("data", [None, [], "firing", 42, [incident_json()]])
def test_anything_but_an_object_is_refused(data) -> None:
    with pytest.raises(InvalidIncident, match="not a JSON object"):
        parse_incident(data, GRAFANA)


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema": "spendwise.incident.v2"},
        {"status": "exploded"},
        {"status": None},
        {"kind": "page-everyone"},
        {"service": "other-api"},
        {"severity": "page"},
        {"severity": None},
        {"category": "billing"},
        {"category": None},  # no category, no evidence plan
        {"alert": None},
        {"alert": ""},
        {"alert": 7},
        {"alert": "   "},
        {"fingerprint": None},
        {"fingerprint": "A7EDBAA05B9B86B7"},
        {"fingerprint": "a7edbaa05b9b86b"},
        {"rule_uid": "../etc/passwd"},
        {"team": "Spend Wise"},
        {"environment": "prod; drop table users"},
        {"environment": 'local"}'},
        {"environment": "x" * 64},
        {"starts_at": None},
        {"starts_at": "yesterday"},
        {"starts_at": "2026-11-15T16:20:30"},
        {"starts_at": "2026-13-45T16:20:30Z"},
        {"starts_at": 1794816030},
        {"ends_at": "2026-11-15T16:21:20Z"},  # a firing incident has no end
        {"received_at": None},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": True},
        {"value": "0.5"},
        {"summary": 5},
    ],
    ids=lambda o: json.dumps(o, default=str)[:60],
)
def test_a_value_outside_the_contract_is_refused(overrides) -> None:
    key = next(iter(overrides))
    data = incident_json(**overrides)
    if key == "summary":  # free text that isn't text is not an error: it is dropped
        assert parse_incident(data, GRAFANA).summary is None
        return
    with pytest.raises(InvalidIncident):
        parse_incident(data, GRAFANA)


def test_an_error_names_the_field_never_the_value() -> None:
    hostile = f"x{INJECTION}"
    with pytest.raises(InvalidIncident) as refused:
        parse_incident(incident_json(status=hostile), GRAFANA)
    assert "status" in str(refused.value) and "IGNORE" not in str(refused.value)


def test_resolved_incidents_carry_their_end() -> None:
    incident = parsed(status="resolved", ends_at="2026-11-15T16:21:20Z", value=0.08)
    assert (incident.status, incident.ends_at) == ("resolved", "2026-11-15T16:21:20Z")


def test_monitoring_failures_have_no_environment_or_value() -> None:
    incident = parsed(kind="datasource_error", environment=None, value=None)
    assert (incident.kind, incident.environment, incident.value) == ("datasource_error", None, None)


def test_free_text_is_made_plain_bounded_and_scrubbed() -> None:
    incident = parsed(
        summary=f"<b>Rate</b>\nhigh\x00\x1b[31m {PATTERN_CANARIES['email']} " + "x " * 400,
        description=f"{PATTERN_CANARIES['authorization']}\n" + "y" * 5000,
        runbook=f"see {PATTERN_CANARIES['database_url']}",
        alert=f"Alert <script>alert(1)</script> {PATTERN_CANARIES['cookie']}",
    )
    for text, limit in (
        (incident.summary, 200),
        (incident.description, 1000),
        (incident.runbook, 1000),
        (incident.alert, 120),
    ):
        assert text and len(text) <= limit
        assert "<" not in text and "\n" not in text and "\x00" not in text and "\x1b" not in text
    blob = json.dumps(incident.for_prompt())
    for canary in (
        "canary-7f3a9c@example.com",
        "abcdefghijklmnop7f3a9c",
        "Canary7f3a9cPw",
        "Zk3q7f3a9c",
    ):
        assert canary not in blob


def test_the_hmac_secret_is_removed_from_text_wherever_it_appears() -> None:
    incident = parse_incident(incident_json(summary=f"leaked {SECRET} here"), GRAFANA, (SECRET,))
    assert SECRET not in json.dumps(incident.for_prompt())


@pytest.mark.parametrize(
    "url",
    [
        "http://evil.test/d/spendwise-overview",
        "http://127.0.0.1:4000/d/spendwise-overview",  # another port
        "https://127.0.0.1:3000/d/spendwise-overview",  # another scheme
        "http://user:secret@127.0.0.1:3000/d/spendwise-overview",
        "http://127.0.0.1:3000/d/a b",
        "javascript:alert(1)",
        "http://[::1/broken",
        42,
    ],
)
def test_a_link_to_anywhere_but_grafana_is_dropped(url) -> None:
    incident = parsed(grafana_url=url, dashboard_url=url, panel_url=url)
    assert incident.grafana_url is incident.dashboard_url is incident.panel_url is None


def test_without_a_configured_grafana_no_link_survives() -> None:
    incident = parse_incident(incident_json(), None)
    assert incident.grafana_url is incident.dashboard_url is incident.panel_url is None


@pytest.mark.parametrize(
    "value",
    [10**400, -(10**400), 10**16, -(10**16), float("inf"), float("-inf"), float("nan"), True, "1"],
)
def test_a_value_that_is_not_a_measurement_is_refused_as_an_invalid_incident(value) -> None:
    # In particular a huge integer: float(10**400) raises OverflowError, which must not escape.
    with pytest.raises(InvalidIncident, match="value is not a finite number"):
        parse_incident(incident_json(value=value), GRAFANA)


@pytest.mark.parametrize(
    ("value", "kept"),
    [(0, 0.0), (7, 7.0), (-2.5, -2.5), (10**15, 1e15), (0.1234567, 0.123457), (None, None)],
)
def test_ordinary_values_are_kept_to_six_decimals(value, kept) -> None:
    assert parse_incident(incident_json(value=value), GRAFANA).value == kept


def test_the_error_for_a_wrong_set_of_fields_counts_the_senders_names_and_never_repeats_them() -> (
    None
):
    hostile = {"A" * 5000 + "\n2026 FAKE LOG LINE": 1, f"x{INJECTION}": 2, "labels": 3}
    with pytest.raises(InvalidIncident) as refused:
        parse_incident(incident_json(**hostile), GRAFANA)
    assert str(refused.value) == "fields differ from the contract (missing [], 3 extra)"
    removed = incident_json()
    del removed["runbook"], removed["team"]
    with pytest.raises(InvalidIncident) as refused:
        parse_incident(removed | {"extra": 1}, GRAFANA)
    # The contract's own names may be listed; they are fixed.
    assert (
        str(refused.value)
        == "fields differ from the contract (missing ['runbook', 'team'], 1 extra)"
    )
