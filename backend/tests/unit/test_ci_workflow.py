"""The CI workflow (.github/workflows/ci.yml): continuous deployment guardrails (Issue #11).

These read the workflow as data; nothing talks to GitHub or AWS. actionlint checks the workflow
syntax and its shell scripts (deploy/aws/README.md).

Two deploy jobs, picked by the repository variable AWS_DEPLOY_MODE, both on GitHub-hosted runners:
- deploy-aws (oidc-gateway): a GitHub OIDC token to the deploy gateway on the instance, for AWS
  Free Tier Projects, whose Service Control Policy denies iam:*Provider*;
- deploy-aws-oidc (oidc-ssm): GitHub OIDC credentials for AWS and SSM Run Command.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
GATEWAY_ENV = ROOT / "deploy" / "aws" / "gateway" / "deploy-gateway.env"
TEST_JOBS = {"backend", "backend-postgres", "frontend", "integration", "e2e"}
DEPLOY_JOBS = {"deploy-aws": "oidc-gateway", "deploy-aws-oidc": "oidc-ssm"}
DEPLOY_STEP = "Deploy the commit through the deploy gateway"
PINNED_ACTION = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text())


@pytest.fixture(scope="module")
def gateway_deploy(workflow) -> dict[str, Any]:
    return workflow["jobs"]["deploy-aws"]


@pytest.fixture(scope="module")
def oidc_deploy(workflow) -> dict[str, Any]:
    return workflow["jobs"]["deploy-aws-oidc"]


def run_scripts(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def step(job: dict[str, Any], name: str) -> dict[str, Any]:
    (found,) = [s for s in job["steps"] if s.get("name") == name]
    return found


def request_function(job: dict[str, Any]) -> str:
    """The body of request_deploy(), which holds the OIDC token."""
    script = step(job, DEPLOY_STEP)["run"]
    return script.split("request_deploy() {", 1)[1].split("\n}\n", 1)[0]


def runs_on(job: dict[str, Any]) -> list[str]:
    labels = job["runs-on"]
    return [labels] if isinstance(labels, str) else labels


def test_ci_still_runs_for_pull_requests_and_pushes_to_main(workflow) -> None:
    triggers = workflow[True]  # YAML 1.1 reads the key "on" as True
    assert triggers["pull_request"]["branches"] == ["main"]
    assert triggers["push"]["branches"] == ["main"]
    assert workflow["permissions"] == {"contents": "read"}


def test_every_job_runs_on_a_github_hosted_runner(workflow) -> None:
    # No self-hosted runner anywhere, in particular none on the production host.
    for name, job in workflow["jobs"].items():
        assert runs_on(job) == ["ubuntu-latest"], name
    assert "self-hosted" not in WORKFLOW.read_text()


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
    # A fork has another github.repository, so its pushes never deploy.
    assert "github.repository == 'allfocusSS/SpendWise'" in condition
    assert f"vars.AWS_DEPLOY_MODE == '{mode}'" in condition
    # Every clause is required: no "||" that could let another event through.
    assert "||" not in condition
    assert "pull_request" not in condition


def test_pull_requests_tags_and_other_branches_never_reach_a_deploy_job(workflow) -> None:
    for name in DEPLOY_JOBS:
        condition = workflow["jobs"][name]["if"]
        # A pull_request run has github.event_name == 'pull_request', so this clause is false;
        # a tag or another branch has another github.ref.
        assert condition.startswith(
            "github.event_name == 'push' && github.ref == 'refs/heads/main'"
        )


def test_only_the_deploy_jobs_can_request_an_oidc_token(workflow, gateway_deploy) -> None:
    # id-token: write and nothing else for the gateway job: no contents, no other permission.
    assert gateway_deploy["permissions"] == {"id-token": "write"}
    oidc = workflow["jobs"]["deploy-aws-oidc"]["permissions"]
    assert oidc == {"contents": "read", "id-token": "write"}
    for name, job in workflow["jobs"].items():
        if name not in DEPLOY_JOBS:
            assert "id-token" not in job.get("permissions", {}), name
    assert "environment" not in gateway_deploy


def test_gateway_job_requests_the_token_itself_with_the_gateway_audience(gateway_deploy) -> None:
    # No action at all (so none to obtain the token): only GitHub's own request URL and token.
    assert all("uses" not in s for s in gateway_deploy["steps"])
    function = request_function(gateway_deploy)
    assert '"$ACTIONS_ID_TOKEN_REQUEST_URL&audience=$DEPLOY_AUDIENCE"' in function
    assert '"$ACTIONS_ID_TOKEN_REQUEST_TOKEN" |' in function
    audience = gateway_deploy["env"]["DEPLOY_AUDIENCE"]
    assert audience == "spendwise-deploy"
    # The same audience the gateway requires.
    assert f"\nDEPLOY_GATEWAY_AUDIENCE={audience}\n" in GATEWAY_ENV.read_text()


def test_gateway_job_never_exposes_the_token(gateway_deploy) -> None:
    script = run_scripts(gateway_deploy)
    function = request_function(gateway_deploy)
    assert "local token" in function
    assert 'echo "::add-mask::$token"' in function
    # Authorization headers reach curl on stdin (-H @-), never on a command line.
    headers = [line for line in script.splitlines() if "Authorization: " in line]
    assert len(headers) == 2 and all(line.rstrip().endswith("|") for line in headers)
    assert function.count("-H @-") == 2
    assert "set -x" not in script
    # The token is only ever printed to the mask command, which the runner consumes. The function
    # is not run in a command substitution, which would capture that line instead.
    assert re.findall(r"echo[^\n]*\$token[^\n]*", script) == ['echo "::add-mask::$token"']
    assert "$(request_deploy" not in script and "`request_deploy" not in script
    assert "GITHUB_OUTPUT" not in function and "GITHUB_ENV" not in function
    assert "tee" not in function and "upload-artifact" not in str(gateway_deploy)


def test_gateway_job_posts_the_tested_commit_and_run(gateway_deploy) -> None:
    assert gateway_deploy["env"]["COMMIT_SHA"] == "${{ github.sha }}"
    script = run_scripts(gateway_deploy)
    assert "^[0-9a-f]{40}$" in script
    assert '--arg sha "$COMMIT_SHA"' in script
    assert '--arg run_id "$GITHUB_RUN_ID"' in script
    assert '--arg run_attempt "$GITHUB_RUN_ATTEMPT"' in script
    assert "'{sha: $sha, run_id: $run_id, run_attempt: $run_attempt}'" in script
    assert '"$PRODUCTION_URL/_deploy"' in request_function(gateway_deploy)


def test_gateway_job_fails_unless_the_gateway_reports_success(gateway_deploy) -> None:
    script = step(gateway_deploy, DEPLOY_STEP)["run"]
    assert "200:success)" in script
    assert 'echo "deployed=true" >> "$GITHUB_OUTPUT"' in script
    # Every other answer (unauthorized, replay_rejected, busy, deploy_failed, health_failed, ...)
    # ends the job with an error.
    other = script.split("\n    *)\n", 1)[1].split(";;", 1)[0]
    assert "exit 1" in other
    verify = step(gateway_deploy, "Verify production health")
    assert verify["if"] == "steps.deploy.outputs.deployed == 'true'"


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


def test_gateway_job_uses_no_github_token(gateway_deploy) -> None:
    assert "github.token" not in str(gateway_deploy) and "GH_TOKEN" not in str(gateway_deploy)


def test_the_gateway_code_is_linted_in_ci(workflow) -> None:
    backend = workflow["jobs"]["backend"]
    assert step(backend, "Lint")["run"] == "uv run ruff check . ../deploy/aws/gateway"
    assert (
        step(backend, "Format check")["run"] == "uv run ruff format --check . ../deploy/aws/gateway"
    )


def test_oidc_job_deploys_the_tested_commit_not_a_branch(oidc_deploy) -> None:
    assert oidc_deploy["env"]["COMMIT_SHA"] == "${{ github.sha }}"
    script = run_scripts(oidc_deploy)
    assert "^[0-9a-f]{40}$" in script
    # The instance must report deploying that same commit.
    assert 'grep -q "^Deploying $COMMIT_SHA "' in script
    assert "CommitSha=main" not in script


def test_oidc_job_sends_the_tested_commit_through_ssm(oidc_deploy) -> None:
    script = run_scripts(oidc_deploy)
    assert '--parameters "CommitSha=$COMMIT_SHA"' in script
    assert '--document-name "$DEPLOY_DOCUMENT"' in script
    assert '--instance-ids "$INSTANCE_ID"' in script


def test_oidc_credentials_come_from_the_role_only(oidc_deploy) -> None:
    (aws,) = [s for s in oidc_deploy["steps"] if "configure-aws-credentials" in s.get("uses", "")]
    inputs = aws["with"]
    assert inputs["role-to-assume"] == "${{ vars.AWS_DEPLOY_ROLE_ARN }}"
    assert inputs["audience"] == "sts.amazonaws.com"
    assert not {"aws-access-key-id", "aws-secret-access-key", "aws-session-token"} & set(inputs)


def test_every_action_is_pinned_to_a_commit(workflow) -> None:
    for name, job in workflow["jobs"].items():
        for s in job.get("steps", []):
            if "uses" in s:
                assert PINNED_ACTION.match(s["uses"]), (name, s["uses"])


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


def test_gateway_polling_is_bounded(gateway_deploy) -> None:
    deploy = step(gateway_deploy, DEPLOY_STEP)
    assert deploy["timeout-minutes"] <= 60
    script = deploy["run"]
    assert "deadline=$((SECONDS + 3300))" in script
    assert 'if [ "$transient" -ge 15 ]; then' in script
    assert "--max-time 30" in script and "--max-time 20" in script
    assert "sleep 20" in script


def test_oidc_result_is_polled_with_a_deadline(oidc_deploy) -> None:
    script = run_scripts(oidc_deploy)
    assert "aws ssm get-command-invocation" in script
    assert "deadline=$((SECONDS + " in script
    assert 'if [ "$status" != Success ]; then' in script
