"""The CI workflow (.github/workflows/ci.yml): continuous deployment guardrails (Issue #11).

These read the workflow as data; nothing talks to GitHub or AWS. actionlint checks the workflow
syntax and its shell scripts (deploy/aws/README.md).

Two deploy jobs, picked by the repository variable AWS_DEPLOY_MODE:
- deploy-aws (self-hosted-runner): on the production instance's own runner, for AWS Free Tier
  Projects, whose Service Control Policy denies iam:*Provider* (so no OIDC provider can exist);
- deploy-aws-oidc (oidc-ssm): GitHub OIDC credentials and SSM Run Command.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
TEST_JOBS = {"backend", "backend-postgres", "frontend", "integration", "e2e"}
DEPLOY_JOBS = {"deploy-aws": "self-hosted-runner", "deploy-aws-oidc": "oidc-ssm"}
RUNNER_LABELS = ["self-hosted", "linux", "spendwise-deploy"]
PINNED_ACTION = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text())


@pytest.fixture(scope="module")
def runner_deploy(workflow) -> dict[str, Any]:
    return workflow["jobs"]["deploy-aws"]


@pytest.fixture(scope="module")
def oidc_deploy(workflow) -> dict[str, Any]:
    return workflow["jobs"]["deploy-aws-oidc"]


def run_scripts(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def runs_on(job: dict[str, Any]) -> list[str]:
    labels = job["runs-on"]
    return [labels] if isinstance(labels, str) else labels


def test_ci_still_runs_for_pull_requests_and_pushes_to_main(workflow) -> None:
    triggers = workflow[True]  # YAML 1.1 reads the key "on" as True
    assert triggers["pull_request"]["branches"] == ["main"]
    assert triggers["push"]["branches"] == ["main"]
    assert workflow["permissions"] == {"contents": "read"}


def test_only_the_deploy_job_uses_the_self_hosted_runner(workflow, runner_deploy) -> None:
    assert runs_on(runner_deploy) == RUNNER_LABELS
    for name, job in workflow["jobs"].items():
        if name != "deploy-aws":
            labels = runs_on(job)
            assert labels == ["ubuntu-latest"], (name, labels)
            assert "self-hosted" not in labels and "spendwise-deploy" not in labels


@pytest.mark.parametrize("job_name", DEPLOY_JOBS)
def test_deploy_waits_for_every_ci_job(workflow, job_name) -> None:
    job = workflow["jobs"][job_name]
    assert job["needs"] == ["all-checks"]
    assert set(workflow["jobs"]["all-checks"]["needs"]) == TEST_JOBS
    # all-checks always runs and fails unless every test job succeeded. Without an always() or
    # failure() override, a job that needs it runs only when it succeeded.
    assert "always()" not in job["if"] and "failure()" not in job["if"]


@pytest.mark.parametrize(("job_name", "mode"), DEPLOY_JOBS.items())
def test_deploy_runs_only_for_a_push_to_main_in_this_repository(workflow, job_name, mode) -> None:
    condition = workflow["jobs"][job_name]["if"]
    assert "github.event_name == 'push'" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert "github.repository == 'allfocusSS/SpendWise'" in condition
    assert f"vars.AWS_DEPLOY_MODE == '{mode}'" in condition
    # Every clause is required: no "||" that could let another event through.
    assert "||" not in condition
    assert "pull_request" not in condition


def test_pull_requests_never_reach_a_deploy_job(workflow) -> None:
    for name in DEPLOY_JOBS:
        condition = workflow["jobs"][name]["if"]
        # A pull_request run has github.event_name == 'pull_request', so this clause is false.
        assert condition.startswith("github.event_name == 'push' &&")


def test_runner_deploy_job_runs_no_actions_and_gets_no_token(runner_deploy) -> None:
    # No checkout and no third-party action on the production host: only the inline steps of
    # this workflow, as it is on main.
    assert all("uses" not in step for step in runner_deploy["steps"])
    assert runner_deploy["permissions"] == {}
    assert "environment" not in runner_deploy


def test_runner_deploy_uses_only_the_narrow_sudo_wrapper(runner_deploy) -> None:
    script = run_scripts(runner_deploy)
    sudo_calls = re.findall(r"\bsudo\b.*", script)
    wrapper = 'sudo -n /usr/local/sbin/spendwise-deploy-sha "$COMMIT_SHA"'
    assert sudo_calls == [wrapper + ' 2>&1 | tee "$RUNNER_TEMP/deploy.log"']


@pytest.mark.parametrize("job_name", DEPLOY_JOBS)
def test_the_tested_commit_is_deployed_not_a_branch(workflow, job_name) -> None:
    job = workflow["jobs"][job_name]
    assert job["env"]["COMMIT_SHA"] == "${{ github.sha }}"
    script = run_scripts(job)
    assert "^[0-9a-f]{40}$" in script
    # The instance must report deploying that same commit.
    assert 'grep -q "^Deploying $COMMIT_SHA "' in script
    assert "spendwise-deploy main" not in script and "CommitSha=main" not in script


def test_oidc_job_sends_the_tested_commit_through_ssm(oidc_deploy) -> None:
    script = run_scripts(oidc_deploy)
    assert '--parameters "CommitSha=$COMMIT_SHA"' in script
    assert '--document-name "$DEPLOY_DOCUMENT"' in script
    assert '--instance-ids "$INSTANCE_ID"' in script


def test_only_the_oidc_job_can_request_an_oidc_token(workflow, oidc_deploy) -> None:
    assert oidc_deploy["permissions"] == {"contents": "read", "id-token": "write"}
    for name, job in workflow["jobs"].items():
        if name != "deploy-aws-oidc":
            assert "id-token" not in job.get("permissions", {}), name


def test_oidc_credentials_come_from_the_role_only(oidc_deploy) -> None:
    (step,) = [s for s in oidc_deploy["steps"] if "configure-aws-credentials" in s.get("uses", "")]
    inputs = step["with"]
    assert inputs["role-to-assume"] == "${{ vars.AWS_DEPLOY_ROLE_ARN }}"
    assert inputs["audience"] == "sts.amazonaws.com"
    assert not {"aws-access-key-id", "aws-secret-access-key", "aws-session-token"} & set(inputs)


def test_no_static_aws_credentials_or_secrets_anywhere() -> None:
    text = WORKFLOW.read_text()
    for forbidden in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "aws-access-key-id",
        "secrets.",
    ):
        assert forbidden not in text


def test_every_action_is_pinned_to_a_commit(workflow) -> None:
    for name, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            if "uses" in step:
                assert PINNED_ACTION.match(step["uses"]), (name, step["uses"])


@pytest.mark.parametrize("job_name", DEPLOY_JOBS)
def test_production_health_is_verified_after_the_deploy(workflow, job_name) -> None:
    script = run_scripts(workflow["jobs"][job_name])
    assert "for path in /api/health /api/health/ready; do" in script
    assert "--retry 12" in script and "--max-time 10" in script
    assert '"$PRODUCTION_URL/" | grep -q \'<div id="root">\'' in script
    assert workflow["jobs"][job_name]["env"]["PRODUCTION_URL"] == "${{ vars.PRODUCTION_URL }}"


@pytest.mark.parametrize("job_name", DEPLOY_JOBS)
def test_deploys_are_bounded_and_never_overlap(workflow, job_name) -> None:
    job = workflow["jobs"][job_name]
    assert job["timeout-minutes"] <= 90
    assert job["concurrency"] == {"group": "deploy-aws-production", "cancel-in-progress": False}


def test_runner_deploy_step_has_its_own_timeout(runner_deploy) -> None:
    (step,) = [s for s in runner_deploy["steps"] if s["name"] == "Deploy the commit"]
    assert step["timeout-minutes"] <= 60


def test_oidc_result_is_polled_with_a_deadline(oidc_deploy) -> None:
    script = run_scripts(oidc_deploy)
    assert "aws ssm get-command-invocation" in script
    assert "deadline=$((SECONDS + " in script
    assert 'if [ "$status" != Success ]; then' in script
