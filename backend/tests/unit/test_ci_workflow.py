"""The CI workflow (.github/workflows/ci.yml): continuous deployment guardrails (Issue #11).

These read the workflow as data; nothing talks to GitHub or AWS. actionlint checks the workflow
syntax and its shell scripts (deploy/aws/README.md).
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
TEST_JOBS = {"backend", "backend-postgres", "frontend", "integration", "e2e"}
PINNED_ACTION = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text())


@pytest.fixture(scope="module")
def deploy(workflow) -> dict[str, Any]:
    return workflow["jobs"]["deploy-aws"]


def steps_using(job: dict[str, Any], action: str) -> list[dict[str, Any]]:
    return [step for step in job["steps"] if step.get("uses", "").startswith(action + "@")]


def run_scripts(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_ci_still_runs_for_pull_requests_and_pushes_to_main(workflow) -> None:
    triggers = workflow[True]  # YAML 1.1 reads the key "on" as True
    assert triggers["pull_request"]["branches"] == ["main"]
    assert triggers["push"]["branches"] == ["main"]
    assert workflow["permissions"] == {"contents": "read"}


def test_deploy_waits_for_every_ci_job(workflow, deploy) -> None:
    assert deploy["needs"] == ["all-checks"]
    all_checks = workflow["jobs"]["all-checks"]
    assert set(all_checks["needs"]) == TEST_JOBS
    # all-checks itself always runs and fails unless every test job succeeded; deploy-aws has no
    # always()/failure() override, so it runs only when all-checks succeeded.
    assert "always()" not in deploy["if"] and "failure()" not in deploy["if"]


def test_deploy_runs_only_for_a_push_to_main_in_this_repository(deploy) -> None:
    condition = deploy["if"]
    assert "github.event_name == 'push'" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert "github.repository == 'allfocusSS/SpendWise'" in condition
    assert "pull_request" not in condition


def test_only_the_deploy_job_can_request_an_oidc_token(workflow, deploy) -> None:
    assert deploy["permissions"] == {"contents": "read", "id-token": "write"}
    for name, job in workflow["jobs"].items():
        if name != "deploy-aws":
            assert "id-token" not in job.get("permissions", {}), name


def test_deploy_job_has_no_environment(deploy) -> None:
    # An environment changes the OIDC subject to ...:environment:NAME, which the role does not
    # trust; the trust policy is keyed on the branch (refs/heads/main).
    assert "environment" not in deploy


def test_aws_credentials_come_from_oidc_only(deploy) -> None:
    (step,) = steps_using(deploy, "aws-actions/configure-aws-credentials")
    inputs = step["with"]
    assert inputs["role-to-assume"] == "${{ vars.AWS_DEPLOY_ROLE_ARN }}"
    assert inputs["audience"] == "sts.amazonaws.com"
    assert not {"aws-access-key-id", "aws-secret-access-key", "aws-session-token"} & set(inputs)
    text = WORKFLOW.read_text()
    assert "AWS_ACCESS_KEY_ID" not in text
    assert "AWS_SECRET_ACCESS_KEY" not in text
    assert "secrets." not in text


def test_every_action_is_pinned_to_a_commit(workflow) -> None:
    for name, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            if "uses" in step:
                assert PINNED_ACTION.match(step["uses"]), (name, step["uses"])


def test_the_tested_commit_is_deployed_not_a_branch(deploy) -> None:
    assert deploy["env"]["COMMIT_SHA"] == "${{ github.sha }}"
    script = run_scripts(deploy)
    assert '--parameters "CommitSha=$COMMIT_SHA"' in script
    assert '--document-name "$DEPLOY_DOCUMENT"' in script
    assert '--instance-ids "$INSTANCE_ID"' in script
    # The instance must report the same commit.
    assert 'grep -q "^Deploying $COMMIT_SHA "' in script


def test_deploy_settings_come_from_repository_variables(deploy) -> None:
    env = deploy["env"]
    assert env["AWS_REGION"] == "${{ vars.AWS_REGION }}"
    assert env["INSTANCE_ID"] == "${{ vars.AWS_INSTANCE_ID }}"
    assert env["DEPLOY_DOCUMENT"] == "${{ vars.AWS_DEPLOY_DOCUMENT }}"
    assert env["PRODUCTION_URL"] == "${{ vars.PRODUCTION_URL }}"
    assert "vars.AWS_DEPLOY_ROLE_ARN != ''" in deploy["if"]


def test_deploy_result_is_polled_with_a_deadline_and_failures_fail_the_job(deploy) -> None:
    script = run_scripts(deploy)
    assert "aws ssm get-command-invocation" in script
    assert "deadline=$((SECONDS + " in script
    assert 'if [ "$status" != Success ]; then' in script
    assert deploy["timeout-minutes"] <= 90


def test_production_health_is_verified_after_the_deploy(deploy) -> None:
    script = run_scripts(deploy)
    assert "for path in /api/health /api/health/ready; do" in script
    assert "--retry 12" in script and "--max-time 10" in script


def test_deploys_never_overlap_or_get_cancelled(deploy) -> None:
    assert deploy["concurrency"] == {
        "group": "deploy-aws-production",
        "cancel-in-progress": False,
    }
