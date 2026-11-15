"""The CI workflow (.github/workflows/ci.yml): it tests every change and deploys nothing.

These read the workflow as data; nothing talks to GitHub or AWS. actionlint checks the workflow
syntax and its shell scripts (deploy/aws/README.md).

Development (Render) deploys main by itself once these checks pass (render.yaml). Production
(AWS) changes only through the manual promotion workflow (test_promote_workflow.py), so no job
here may reach the production deploy gateway or request an OIDC token.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
TEST_JOBS = {
    "backend",
    "backend-postgres",
    "frontend",
    "integration",
    "e2e",
    "observability",
    "dashboard",
    "alerts",
}
PINNED_ACTION = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text())


def step(job: dict[str, Any], name: str) -> dict[str, Any]:
    (found,) = [s for s in job["steps"] if s.get("name") == name]
    return found


def runs_on(job: dict[str, Any]) -> list[str]:
    labels = job["runs-on"]
    return [labels] if isinstance(labels, str) else labels


def test_ci_still_runs_for_pull_requests_and_pushes_to_main(workflow) -> None:
    triggers = workflow[True]  # YAML 1.1 reads the key "on" as True
    assert triggers["pull_request"]["branches"] == ["main"]
    assert triggers["push"]["branches"] == ["main"]
    assert workflow["permissions"] == {"contents": "read"}


def test_ci_runs_every_test_job_and_the_gate(workflow) -> None:
    assert set(workflow["jobs"]) == TEST_JOBS | {"all-checks"}
    gate = workflow["jobs"]["all-checks"]
    assert gate["name"] == "All checks passed"  # the name the promotion workflow requires
    assert set(gate["needs"]) == TEST_JOBS
    assert gate["if"] == "always()"
    fail = step(gate, "Fail unless every job succeeded")
    for result in ("failure", "cancelled", "skipped"):
        assert f"contains(needs.*.result, '{result}')" in fail["if"]
    assert fail["run"] == "exit 1"


def test_the_observability_job_runs_the_opentelemetry_smoke_test(workflow) -> None:
    job = workflow["jobs"]["observability"]
    assert job["name"] == "Observability (OpenTelemetry)"
    run = step(job, "OpenTelemetry pipeline (builds the image, Compose stack + Collector)")
    assert run["run"] == "make observability"
    makefile = (ROOT / "Makefile").read_text()
    assert "observability:\n\tcd backend && uv run pytest observability_smoke $(ARGS)" in makefile
    # Its stack is removed even if the run was interrupted, Collector and volume included.
    cleanup = step(job, "Remove the test stack and its volume")
    assert cleanup["if"] == "always()"
    assert cleanup["run"] == "uv run python -m integration.stack down --observability"
    assert cleanup["env"]["SPENDWISE_IT_PROJECT"] == "spendwise-otel"
    # Logs (with what the Collector printed) only when it fails; nothing else leaves the run.
    upload = step(job, "Upload Compose logs")
    assert upload["if"] == "failure()"
    # The workflow's read-only token, nothing more.
    assert "permissions" not in job
    assert job["timeout-minutes"] <= 30


def test_the_dashboard_job_runs_the_dashboard_smoke_test(workflow) -> None:
    job = workflow["jobs"]["dashboard"]
    assert job["name"] == "Observability Dashboard"
    assert step(job, "Dashboard (builds the image, Compose stack + Grafana LGTM)")["run"] == (
        "make dashboard"
    )
    makefile = (ROOT / "Makefile").read_text()
    assert "dashboard:\n\tcd backend && uv run pytest dashboard_smoke $(ARGS)" in makefile
    cleanup = step(job, "Remove the test stack and its volume")
    assert cleanup["if"] == "always()"
    assert cleanup["run"] == "uv run python -m integration.stack down --dashboard"
    assert cleanup["env"]["SPENDWISE_IT_PROJECT"] == "spendwise-dashboard"
    assert step(job, "Upload Compose logs")["if"] == "failure()"
    # The workflow's read-only token only: no OIDC token, nothing deployed.
    assert "permissions" not in job
    assert job["timeout-minutes"] <= 30


def test_the_alerts_job_runs_the_alert_smoke_test(workflow) -> None:
    job = workflow["jobs"]["alerts"]
    assert job["name"] == "Observability Alerts"
    name = "Alerts (builds the image, Compose stack + Grafana LGTM + alert receiver)"
    assert step(job, name)["run"] == "make alerts"
    makefile = (ROOT / "Makefile").read_text()
    assert "alerts:\n\tcd backend && uv run pytest alerts_smoke $(ARGS)" in makefile
    cleanup = step(job, "Remove the test stack and its volume")
    assert cleanup["if"] == "always()"
    assert cleanup["run"] == "uv run python -m integration.stack down --dashboard"
    assert cleanup["env"]["SPENDWISE_IT_PROJECT"] == "spendwise-alerts"
    assert step(job, "Upload Compose logs")["if"] == "failure()"
    # Parallel with the other jobs, and the workflow's read-only token only: no OIDC token,
    # nothing deployed.
    assert "needs" not in job
    assert "permissions" not in job
    assert job["timeout-minutes"] <= 30


def test_every_job_runs_on_a_github_hosted_runner(workflow) -> None:
    # No self-hosted runner anywhere, in particular none on the production host.
    for name, job in workflow["jobs"].items():
        assert runs_on(job) == ["ubuntu-latest"], name
    assert "self-hosted" not in WORKFLOW.read_text()


def test_no_job_can_deploy_production(workflow) -> None:
    # Neither a push to main nor a pull request: no job may get an OIDC token, and nothing calls
    # the deploy gateway, AWS or the production URL.
    for name, job in workflow["jobs"].items():
        assert "id-token" not in job.get("permissions", {}), name
        assert "environment" not in job, name
    text = WORKFLOW.read_text()
    for forbidden in (
        "id-token",
        "/_deploy",
        "ACTIONS_ID_TOKEN_REQUEST",
        "PRODUCTION_URL",
        "AWS_DEPLOY_MODE",
        "configure-aws-credentials",
        "aws ssm",
        "spendwise-deploy",
        "nip.io",
    ):
        assert forbidden not in text, forbidden


@pytest.mark.parametrize("event", ["push", "pull_request"])
def test_every_job_is_a_test_job_whatever_the_event(workflow, event) -> None:
    # No job is conditional on the event (as the old push-only deploy jobs were): a push to
    # main and a pull request run exactly the same jobs, and those jobs only test.
    for name, job in workflow["jobs"].items():
        assert event not in str(job.get("if", "")), name


def test_no_static_aws_credentials_tokens_or_secrets_anywhere() -> None:
    text = WORKFLOW.read_text()
    for forbidden in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "aws-access-key-id",
        "secrets.",
        "ghp_",
        "github_pat_",
    ):
        assert forbidden not in text


def test_the_gateway_and_alert_receiver_code_is_linted_in_ci(workflow) -> None:
    backend = workflow["jobs"]["backend"]
    paths = ". ../deploy/aws/gateway ../deploy/observability/alert-receiver"
    assert step(backend, "Lint")["run"] == f"uv run ruff check {paths}"
    assert step(backend, "Format check")["run"] == f"uv run ruff format --check {paths}"


def test_every_action_is_pinned_to_a_commit(workflow) -> None:
    for name, job in workflow["jobs"].items():
        for s in job.get("steps", []):
            if "uses" in s:
                assert PINNED_ACTION.match(s["uses"]), (name, s["uses"])


def test_runs_on_main_are_never_cancelled(workflow) -> None:
    # Each commit on main gets a complete result, which the promotion workflow looks up.
    concurrency = workflow["concurrency"]
    assert "github.sha" in concurrency["group"]
    assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
