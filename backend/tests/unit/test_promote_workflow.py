"""The production promotion workflow (.github/workflows/promote-production.yml).

Production (AWS) changes only when someone runs this workflow by hand, on main. It promotes the
commit development (Render) already runs, once CI passed for it, through the OIDC deploy
gateway, then checks production runs it (docs/environments.md).

Most tests run the workflow's own shell steps with stand-ins for gh, curl, git and sleep, so
they check what the steps do, not only what they say. Nothing talks to GitHub, Render or AWS.
actionlint checks the syntax and shellcheck the scripts (deploy/aws/README.md).
"""

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "promote-production.yml"
GATEWAY_DIR = ROOT / "deploy" / "aws" / "gateway"
GATEWAY_ENV = GATEWAY_DIR / "deploy-gateway.env"

SHA = "835f9e36979e446878df74d9c9340bbd3ad46922"
OLD_SHA = "1a87352a1a87352a1a87352a1a87352a1a87352a"
NEW_SHA = "ebf7f89ebf7f89ebf7f89ebf7f89ebf7f89ebf7f"
REPOSITORY = "allfocusSS/SpendWise"
DEVELOPMENT = "https://spendwise-amyx.onrender.com"
PRODUCTION = "https://54.79.77.189.nip.io"
TOKEN = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.c2lnbmF0dXJl"
TOKEN_URL = "https://token.test/request?api-version=2.0"
DEPLOY_STEP = "Deploy the commit through the deploy gateway"

needs_jq = pytest.mark.skipif(shutil.which("jq") is None, reason="the workflow's scripts use jq")


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text())


def job(workflow, name: str) -> dict[str, Any]:
    return workflow["jobs"][name]


def step(job: dict[str, Any], name: str) -> dict[str, Any]:
    (found,) = [s for s in job["steps"] if s.get("name") == name]
    return found


def run_scripts(job: dict[str, Any]) -> str:
    return "\n".join(s.get("run", "") for s in job["steps"])


# --- Stand-ins for the tools the steps call ------------------------------------------------

# gh api: the head of main, CI's runs for a commit, and a run's jobs, from files.
GH = """#!/bin/bash
printf '%s\\n' "$*" >> "$STUB_DIR/gh-args"
case "$*" in
  *git/ref/heads/main*) cat "$STUB_DIR/head" ;;
  *actions/workflows/ci.yml/runs*) cat "$STUB_DIR/runs.json" ;;
  *actions/runs/*/jobs*) cat "$STUB_DIR/jobs.json" ;;
  *) echo "unexpected: gh $*" >&2; exit 1 ;;
esac
"""

# curl: answers by URL from "<key>.<n>" (the n-th call) or "<key>": an HTTP status on the first
# line, then the body. No file: no connection. -o/-w behave like curl's, -f fails on >= 400.
# Records every command line, and what was sent on stdin (-H @-).
CURL = """#!/bin/bash
printf '%s\\n' "$*" >> "$STUB_DIR/curl-argv"
out="" url="" fail=false
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out=$2; shift 2 ;;
    -H) if [ "$2" = @- ]; then cat >> "$STUB_DIR/curl-stdin"; fi; shift 2 ;;
    --data) printf '%s\\n' "$2" >> "$STUB_DIR/curl-data"; shift 2 ;;
    -w | --max-time | --retry | --retry-delay) shift 2 ;;
    -f* | -*f*) fail=true; shift ;;
    -*) shift ;;
    *) url=$1; shift ;;
  esac
done
key=$(printf %s "${url#https://}" | tr -c 'A-Za-z0-9' '_')
n=$(($(cat "$STUB_DIR/count.$key" 2> /dev/null || echo 0) + 1))
echo "$n" > "$STUB_DIR/count.$key"
file="$STUB_DIR/$key.$n"
[ -f "$file" ] || file="$STUB_DIR/$key"
[ -f "$file" ] || exit 7
code=$(head -n 1 "$file")
body=$(tail -n +2 "$file")
if [ -n "$out" ]; then
  printf '%s' "$body" > "$out"
  printf '%s' "$code"
  exit 0
fi
if $fail && [ "$code" -ge 400 ]; then exit 22; fi
printf '%s\\n' "$body"
"""

GIT = """#!/bin/bash
[ "$1" = ls-remote ] || exit 1
printf '%s\\trefs/heads/main\\n' "$(cat "$STUB_DIR/head")"
"""

SLEEP = """#!/bin/bash
[ -n "${STUB_SLEEP:-}" ] && /bin/sleep "$STUB_SLEEP"
exit 0
"""


def key(url: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", url.removeprefix("https://"))


class Steps:
    """Runs one step's script like GitHub does (bash -eo pipefail) with the stand-ins."""

    def __init__(self, workflow: dict[str, Any], tmp_path: Path) -> None:
        self.workflow = workflow
        self.dir = tmp_path
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(parents=True)
        for name, body in {"gh": GH, "curl": CURL, "git": GIT, "sleep": SLEEP}.items():
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)
        jq = shutil.which("jq")
        self.path = f"{bin_dir}:{Path(jq).parent if jq else '/usr/bin'}:/usr/bin:/bin"
        self.summary = tmp_path / "summary.md"
        self.head(SHA)

    def head(self, sha: str) -> None:
        (self.dir / "head").write_text(sha + "\n")

    def answer(self, url: str, *answers: tuple[int, Any]) -> None:
        """What GET/POST url returns: one answer for every call, or one per call in order."""
        for n, (code, body) in enumerate(answers, start=1):
            text = body if isinstance(body, str) else json.dumps(body)
            name = key(url) if len(answers) == 1 else f"{key(url)}.{n}"
            (self.dir / name).write_text(f"{code}\n{text}")

    def json(self, name: str, data: Any) -> None:
        (self.dir / name).write_text(json.dumps(data))

    def read(self, name: str) -> str:
        path = self.dir / name
        return path.read_text() if path.exists() else ""

    def calls(self, url: str) -> int:
        return int(self.read(f"count.{key(url)}") or 0)

    def run(
        self,
        job_name: str,
        step_name: str,
        env: dict[str, str] | None = None,
        replacements: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        script = step(job(self.workflow, job_name), step_name)["run"]
        for old, new in (replacements or {}).items():
            assert old in script
            script = script.replace(old, new)
        path = self.dir / "step.sh"
        path.write_text(script)
        base = {
            "PATH": self.path,
            "HOME": str(self.dir),
            "STUB_DIR": str(self.dir),
            "RUNNER_TEMP": str(self.dir),
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "GITHUB_OUTPUT": str(self.dir / "output"),
            "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_RUN_ID": "123456789",
            "GITHUB_RUN_ATTEMPT": "1",
            "COMMIT_SHA": SHA,
            "DEVELOPMENT_URL": DEVELOPMENT,
            "PRODUCTION_URL": PRODUCTION,
            "DEPLOY_MODE": "oidc-gateway",
            "DEPLOY_AUDIENCE": "spendwise-deploy",
            "GH_TOKEN": "stand-in",
            "ACTIONS_ID_TOKEN_REQUEST_URL": TOKEN_URL,
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "request-token",
        }
        return subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(path)],
            capture_output=True,
            text=True,
            env=base | (env or {}),
            timeout=120,
        )


@pytest.fixture
def steps(workflow, tmp_path) -> Steps:
    return Steps(workflow, tmp_path)


def errors(result: subprocess.CompletedProcess) -> str:
    return "\n".join(line for line in result.stdout.splitlines() if line.startswith("::error::"))


# --- Trigger, permissions, order -----------------------------------------------------------


def test_it_is_a_manual_workflow_and_nothing_else(workflow) -> None:
    assert workflow["name"] == "Promote Development to Production"
    triggers = workflow[True]  # YAML 1.1 reads the key "on" as True
    assert triggers == {"workflow_dispatch": None}
    # No inputs: nobody can type a commit, a branch or a URL to promote.
    assert "inputs" not in (triggers["workflow_dispatch"] or {})


def test_every_job_gets_only_the_permissions_it_needs(workflow) -> None:
    assert workflow["permissions"] == {}
    assert job(workflow, "verify")["permissions"] == {"actions": "read", "contents": "read"}
    # The OIDC token, and nothing else, only for the job that talks to the gateway.
    assert job(workflow, "deploy")["permissions"] == {"id-token": "write"}
    assert job(workflow, "verify-production")["permissions"] == {}
    for name, j in workflow["jobs"].items():
        if name != "deploy":
            assert "id-token" not in j["permissions"], name


def test_production_is_touched_only_after_ci_and_development_were_verified(workflow) -> None:
    assert set(workflow["jobs"]) == {"verify", "deploy", "verify-production"}
    assert "needs" not in job(workflow, "verify")
    assert job(workflow, "deploy")["needs"] == ["verify"]
    assert job(workflow, "verify-production")["needs"] == ["deploy"]
    # No always()/failure() override: a job runs only if the one before it succeeded.
    for name, j in workflow["jobs"].items():
        assert "if" not in j, name
        for s in j["steps"]:
            assert "if" not in s, (name, s.get("name"))
    verify = [s["name"] for s in job(workflow, "verify")["steps"]]
    assert verify == [
        "Check the promotion request",
        "Require main to be at this commit",
        "Require a successful CI run for this commit",
        "Wait for development to run this commit",
        "Verify development health and readiness",
    ]


def test_promotions_never_overlap_and_are_never_cancelled_half_way(workflow) -> None:
    assert workflow["concurrency"] == {"group": "production-promotion", "cancel-in-progress": False}


def test_it_promotes_the_exact_commit_of_the_run(workflow) -> None:
    assert workflow["env"]["COMMIT_SHA"] == "${{ github.sha }}"
    assert workflow["run-name"] == "Promote ${{ github.sha }} to production"
    text = WORKFLOW.read_text()
    assert "inputs." not in text and "github.event.inputs" not in text


def test_development_and_production_urls(workflow) -> None:
    assert workflow["env"]["DEVELOPMENT_URL"] == DEVELOPMENT
    assert workflow["env"]["PRODUCTION_URL"] == "${{ vars.PRODUCTION_URL }}"


def test_every_job_runs_on_a_github_hosted_runner_and_is_bounded(workflow) -> None:
    for name, j in workflow["jobs"].items():
        assert j["runs-on"] == "ubuntu-latest", name
        assert j["timeout-minutes"] <= 65, name
    assert "self-hosted" not in WORKFLOW.read_text()


def test_no_action_no_secret_and_no_long_lived_credential(workflow) -> None:
    # No third-party code runs anywhere in this workflow, least of all next to the OIDC token.
    for name, j in workflow["jobs"].items():
        assert all("uses" not in s for s in j["steps"]), name
        # A GitHub environment would change the token's subject, which the gateway pins.
        assert "environment" not in j, name
    text = WORKFLOW.read_text()
    for forbidden in (
        "secrets.",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "aws-access-key-id",
        "ghp_",
        "github_pat_",
        "PAT",
    ):
        assert forbidden not in text, forbidden
    # The read-only GITHUB_TOKEN only where the GitHub API is read; never in the deploy job.
    assert job(workflow, "verify")["env"]["GH_TOKEN"] == "${{ github.token }}"
    for name in ("deploy", "verify-production"):
        assert "github.token" not in str(job(workflow, name)) and "GH_TOKEN" not in str(
            job(workflow, name)
        )


# --- The gateway trusts exactly this workflow ----------------------------------------------


def gateway_module():
    spec = importlib.util.spec_from_file_location(
        "spendwise_deploy_gateway_for_workflow_tests", GATEWAY_DIR / "spendwise_deploy_gateway.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up there
    spec.loader.exec_module(module)
    return module


def test_the_gateway_trusts_this_workflow_on_main_for_manual_runs_only(workflow) -> None:
    settings = dict(
        line.split("=", 1)
        for line in GATEWAY_ENV.read_text().splitlines()
        if line and not line.startswith("#")
    )
    assert settings["DEPLOY_GATEWAY_WORKFLOW"] == ".github/workflows/" + WORKFLOW.name
    assert settings["DEPLOY_GATEWAY_REF"] == "refs/heads/main"
    assert settings["DEPLOY_GATEWAY_REPOSITORY"] == REPOSITORY
    # The event the gateway requires is the only trigger of this workflow.
    assert gateway_module().EVENT_NAME == "workflow_dispatch"
    assert list(workflow[True]) == ["workflow_dispatch"]
    # The audience the workflow asks for is the one the gateway requires.
    audience = job(workflow, "deploy")["env"]["DEPLOY_AUDIENCE"]
    assert audience == settings["DEPLOY_GATEWAY_AUDIENCE"] == "spendwise-deploy"


# --- verify: the request -------------------------------------------------------------------


@needs_jq
def test_a_manual_run_on_main_passes_the_request_check(steps) -> None:
    result = steps.run("verify", "Check the promotion request")
    assert result.returncode == 0, result.stdout + result.stderr


@needs_jq
@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"GITHUB_REF": "refs/heads/feature"}, "from main only"),
        ({"GITHUB_REF": "refs/tags/v1.0.0"}, "from main only"),
        ({"GITHUB_REF": "refs/pull/42/merge"}, "from main only"),
        ({"GITHUB_EVENT_NAME": "push"}, "started by hand only"),
        ({"GITHUB_EVENT_NAME": "pull_request"}, "started by hand only"),
        ({"GITHUB_REPOSITORY": "someone/SpendWise"}, "allfocusSS/SpendWise only"),
        ({"COMMIT_SHA": "main"}, "Unexpected commit SHA"),
        ({"COMMIT_SHA": SHA[:12]}, "Unexpected commit SHA"),
        ({"DEPLOY_MODE": ""}, "AWS_DEPLOY_MODE"),
        ({"DEPLOY_MODE": "oidc-ssm"}, "AWS_DEPLOY_MODE"),
        ({"PRODUCTION_URL": ""}, "PRODUCTION_URL is missing or invalid"),
        ({"PRODUCTION_URL": "http://54.79.77.189.nip.io"}, "PRODUCTION_URL is missing or invalid"),
        ({"PRODUCTION_URL": PRODUCTION + "/"}, "PRODUCTION_URL is missing or invalid"),
        ({"PRODUCTION_URL": DEVELOPMENT}, "is the development URL"),
    ],
)
def test_anything_else_is_refused_before_any_check(steps, env, message) -> None:
    result = steps.run("verify", "Check the promotion request", env)
    assert result.returncode == 1
    assert message in errors(result)


@needs_jq
def test_main_must_be_at_the_promoted_commit(steps) -> None:
    assert steps.run("verify", "Require main to be at this commit").returncode == 0
    steps.head(NEW_SHA)
    result = steps.run("verify", "Require main to be at this commit")
    assert result.returncode == 1
    assert f"main is at {NEW_SHA}, not {SHA}" in errors(result)


# --- verify: CI ----------------------------------------------------------------------------

CI_STEP = "Require a successful CI run for this commit"


def ci_run(run_id=111, sha=SHA, status="completed", conclusion="success", **extra) -> dict:
    return {
        "id": run_id,
        "head_sha": sha,
        "event": "push",
        "head_branch": "main",
        "status": status,
        "conclusion": conclusion,
        "created_at": "2026-11-15T10:00:00Z",
        "html_url": f"https://github.com/{REPOSITORY}/actions/runs/{run_id}",
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
    } | extra


def ci_jobs(gate="success") -> dict:
    jobs = [{"name": n, "conclusion": "success"} for n in ("Backend (lint + test)", "End-to-end")]
    if gate is not None:
        jobs.append({"name": "All checks passed", "conclusion": gate})
    return {"jobs": jobs}


@needs_jq
def test_a_commit_whose_ci_push_run_passed_is_accepted(steps) -> None:
    steps.json("runs.json", {"workflow_runs": [ci_run()]})
    steps.json("jobs.json", ci_jobs())
    result = steps.run("verify", CI_STEP)
    assert result.returncode == 0, result.stdout + result.stderr
    # It asked GitHub for push runs of exactly this commit on main, and for that run's jobs.
    (runs, jobs) = steps.read("gh-args").splitlines()
    assert f"repos/{REPOSITORY}/actions/workflows/ci.yml/runs" in runs
    assert f"-f head_sha={SHA}" in runs and "-f event=push" in runs and "-f branch=main" in runs
    assert f"repos/{REPOSITORY}/actions/runs/111/jobs" in jobs
    assert "CI passed" in steps.summary.read_text()


@needs_jq
@pytest.mark.parametrize(
    ("runs", "gate", "message"),
    [
        pytest.param([], "success", "No CI run for a push of", id="no-ci-run"),
        pytest.param(
            [ci_run(status="in_progress", conclusion=None)],
            "success",
            "is in_progress (none), not a success",
            id="ci-still-running",
        ),
        pytest.param(
            [ci_run(status="queued", conclusion=None)], "success", "is queued", id="ci-queued"
        ),
        pytest.param([ci_run(conclusion="failure")], "failure", "(failure)", id="ci-failed"),
        pytest.param([ci_run(conclusion="cancelled")], "success", "(cancelled)", id="cancelled"),
        pytest.param([ci_run(sha=OLD_SHA)], "success", "No CI run", id="another-commit"),
        pytest.param([ci_run(event="pull_request")], "success", "No CI run", id="pull-request-run"),
        pytest.param(
            [ci_run(event="workflow_dispatch")], "success", "No CI run", id="manual-ci-run"
        ),
        pytest.param([ci_run(head_branch="feature")], "success", "No CI run", id="other-branch"),
        pytest.param(
            [ci_run(head_repository={"full_name": "someone/SpendWise"})],
            "success",
            "No CI run",
            id="fork",
        ),
        pytest.param(
            [
                ci_run(111, created_at="2026-11-15T10:00:00Z"),
                ci_run(222, conclusion="failure", created_at="2026-11-15T11:00:00Z"),
            ],
            "success",
            "(failure)",
            id="the-newest-run-failed",
        ),
        pytest.param(
            [ci_run()], "failure", '"All checks passed" in CI run 111 is failure', id="gate-failed"
        ),
        pytest.param([ci_run()], "skipped", "is skipped", id="gate-skipped"),
        pytest.param([ci_run()], None, "is missing", id="gate-missing"),
    ],
)
def test_promotion_fails_unless_ci_passed_for_this_commit(steps, runs, gate, message) -> None:
    steps.json("runs.json", {"workflow_runs": runs})
    steps.json("jobs.json", ci_jobs(gate))
    result = steps.run("verify", CI_STEP)
    assert result.returncode == 1
    assert message in errors(result)


# --- verify: development -------------------------------------------------------------------

WAIT_STEP = "Wait for development to run this commit"
DEV_STEP = "Verify development health and readiness"


def meta(environment: str, version: str | None) -> tuple[int, dict]:
    return 200, {"environment": environment, "version": version}


@needs_jq
def test_promotion_waits_for_development_to_run_the_commit(steps) -> None:
    steps.answer(
        f"{DEVELOPMENT}/api/meta",
        (404, {"detail": "Not Found"}),  # still the deploy before /api/meta existed
        (503, "Service Unavailable"),  # waking up
        meta("development", OLD_SHA),  # the previous commit
        meta("development", SHA),
    )
    result = steps.run("verify", WAIT_STEP)
    assert result.returncode == 0, result.stdout + result.stderr
    assert steps.calls(f"{DEVELOPMENT}/api/meta") == 4
    assert f"version {OLD_SHA}" in result.stdout


@needs_jq
def test_a_development_that_is_not_development_stops_the_promotion(steps) -> None:
    # E.g. APP_ENV missing on Render, so the image's default (production) applies.
    steps.answer(f"{DEVELOPMENT}/api/meta", meta("production", SHA))
    result = steps.run("verify", WAIT_STEP)
    assert result.returncode == 1
    assert "reports environment 'production', not development" in errors(result)
    assert steps.calls(f"{DEVELOPMENT}/api/meta") == 1


@needs_jq
def test_promotion_stops_when_main_moves_on_while_waiting(steps) -> None:
    steps.answer(f"{DEVELOPMENT}/api/meta", meta("development", OLD_SHA))
    steps.head(NEW_SHA)
    result = steps.run("verify", WAIT_STEP)
    assert result.returncode == 1
    assert f"main moved on to {NEW_SHA}" in errors(result)


@needs_jq
def test_waiting_for_development_has_a_hard_limit(workflow, steps) -> None:
    script = step(job(workflow, "verify"), WAIT_STEP)
    assert "deadline=$((SECONDS + 1800))" in script["run"]
    assert script["timeout-minutes"] == 35
    assert "sleep 30" in script["run"] and "--max-time 90" in script["run"]
    # The same loop with a 2-second limit: it gives up and fails.
    steps.answer(f"{DEVELOPMENT}/api/meta", meta("development", OLD_SHA))
    result = steps.run(
        "verify",
        WAIT_STEP,
        {"STUB_SLEEP": "1"},
        replacements={"deadline=$((SECONDS + 1800))": "deadline=$((SECONDS + 2))"},
    )
    assert result.returncode == 1
    assert f"Development did not report {SHA} within 30 minutes" in errors(result)


@needs_jq
def test_development_must_be_healthy_and_ready(steps) -> None:
    steps.answer(f"{DEVELOPMENT}/api/health", (200, {"status": "ok"}))
    steps.answer(f"{DEVELOPMENT}/api/health/ready", (200, {"status": "ok"}))
    steps.answer(f"{DEVELOPMENT}/api/meta", meta("development", SHA))
    result = steps.run("verify", DEV_STEP)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"runs {SHA}, healthy and ready" in steps.summary.read_text()


@needs_jq
@pytest.mark.parametrize(
    ("health", "ready", "dev_meta", "message"),
    [
        (
            (200, {"status": "ok"}),
            (503, {"status": "database unavailable"}),
            meta("development", SHA),
            "/api/health/ready is not ok",
        ),
        (
            (500, "error"),
            (200, {"status": "ok"}),
            meta("development", SHA),
            "/api/health is not ok",
        ),
        (
            (200, {"status": "starting"}),
            (200, {"status": "ok"}),
            meta("development", SHA),
            "/api/health is not ok",
        ),
        (
            (200, {"status": "ok"}),
            (200, {"status": "ok"}),
            meta("development", NEW_SHA),
            "no longer reports",
        ),
        (
            (200, {"status": "ok"}),
            (200, {"status": "ok"}),
            meta("production", SHA),
            "no longer reports",
        ),
    ],
)
def test_an_unhealthy_development_stops_the_promotion(
    steps, health, ready, dev_meta, message
) -> None:
    steps.answer(f"{DEVELOPMENT}/api/health", health)
    steps.answer(f"{DEVELOPMENT}/api/health/ready", ready)
    steps.answer(f"{DEVELOPMENT}/api/meta", dev_meta)
    result = steps.run("verify", DEV_STEP)
    assert result.returncode == 1
    assert message in errors(result)


# --- deploy --------------------------------------------------------------------------------


def request_function(workflow) -> str:
    """The body of request_deploy(), which holds the OIDC token."""
    script = step(job(workflow, "deploy"), DEPLOY_STEP)["run"]
    return script.split("request_deploy() {", 1)[1].split("\n}\n", 1)[0]


def gateway(status: str, code: int = 200) -> tuple[int, dict]:
    return code, {"status": status, "sha": SHA, "run_id": "123456789", "run_attempt": "1"}


def token_answers(steps: Steps) -> None:
    steps.answer(f"{TOKEN_URL}&audience=spendwise-deploy", (200, {"value": TOKEN}))


def test_the_deploy_job_requests_its_own_token_with_the_gateway_audience(workflow) -> None:
    function = request_function(workflow)
    assert '"$ACTIONS_ID_TOKEN_REQUEST_URL&audience=$DEPLOY_AUDIENCE"' in function
    assert '"$ACTIONS_ID_TOKEN_REQUEST_TOKEN" |' in function
    assert '"$PRODUCTION_URL/_deploy"' in function


def test_the_deploy_job_never_exposes_the_token(workflow) -> None:
    deploy = job(workflow, "deploy")
    script = run_scripts(deploy)
    function = request_function(workflow)
    assert "local token" in function
    assert 'echo "::add-mask::$token"' in function
    # Authorization headers reach curl on stdin (-H @-), never on a command line.
    headers = [line for line in script.splitlines() if "Authorization: " in line]
    assert len(headers) == 2 and all(line.rstrip().endswith("|") for line in headers)
    assert function.count("-H @-") == 2
    assert "set -x" not in script
    assert re.findall(r"echo[^\n]*\$token[^\n]*", script) == ['echo "::add-mask::$token"']
    assert "$(request_deploy" not in script and "`request_deploy" not in script
    assert "GITHUB_OUTPUT" not in function and "GITHUB_ENV" not in function
    assert "tee" not in function and "upload-artifact" not in str(deploy)


@needs_jq
def test_a_deploy_is_started_polled_and_succeeds(steps) -> None:
    token_answers(steps)
    steps.answer(
        f"{PRODUCTION}/_deploy",
        gateway("running", 202),
        gateway("running", 202),
        gateway("success"),
    )
    result = steps.run("deploy", DEPLOY_STEP)
    assert result.returncode == 0, result.stdout + result.stderr
    assert steps.calls(f"{PRODUCTION}/_deploy") == 3
    # Each request had its own token, sent on stdin; the body names this exact commit and run.
    sent = steps.read("curl-stdin")
    assert sent.count(f"Authorization: Bearer {TOKEN}") == 3
    assert sent.count("Authorization: bearer request-token") == 3
    bodies = [json.loads(line) for line in steps.read("curl-data").splitlines()]
    assert bodies == [{"sha": SHA, "run_id": "123456789", "run_attempt": "1"}] * 3
    # The token is never on a command line, nor printed except to the mask command.
    assert TOKEN not in steps.read("curl-argv")
    assert [line for line in result.stdout.splitlines() if TOKEN in line] == [
        f"::add-mask::{TOKEN}"
    ] * 3
    assert TOKEN not in result.stderr


@needs_jq
@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (gateway("superseded"), "no longer the head of main"),
        ((401, {"status": "unauthorized"}), "reported unauthorized"),
        ((409, {"status": "replay_rejected"}), "reported replay_rejected"),
        ((409, {"status": "busy"}), "reported busy"),
        (gateway("deploy_failed"), "reported deploy_failed"),
        (gateway("health_failed"), "reported health_failed"),
        (gateway("timeout"), "reported timeout"),
        (gateway("interrupted"), "reported interrupted"),
        ((404, "not found"), "reported HTTP 404"),
    ],
)
def test_anything_but_success_fails_the_promotion(steps, answer, message) -> None:
    token_answers(steps)
    steps.answer(f"{PRODUCTION}/_deploy", gateway("running", 202), answer)
    result = steps.run("deploy", DEPLOY_STEP)
    assert result.returncode == 1
    assert message in errors(result)


@needs_jq
def test_transient_gateway_failures_are_retried_a_bounded_number_of_times(workflow, steps) -> None:
    token_answers(steps)
    steps.answer(
        f"{PRODUCTION}/_deploy", gateway("running", 202), (502, ""), (503, ""), gateway("success")
    )
    assert steps.run("deploy", DEPLOY_STEP).returncode == 0

    other = Steps(workflow, steps.dir / "always-502")
    token_answers(other)
    other.answer(f"{PRODUCTION}/_deploy", (502, "Bad Gateway"))
    result = other.run("deploy", DEPLOY_STEP)
    assert result.returncode == 1
    assert "did not answer" in errors(result)
    assert other.calls(f"{PRODUCTION}/_deploy") == 15


def test_polling_the_gateway_is_bounded(workflow) -> None:
    deploy = step(job(workflow, "deploy"), DEPLOY_STEP)
    assert deploy["timeout-minutes"] <= 60
    script = deploy["run"]
    assert "deadline=$((SECONDS + 3300))" in script
    assert 'if [ "$transient" -ge 15 ]; then' in script
    assert "--max-time 30" in script and "--max-time 20" in script
    assert "sleep 20" in script


@needs_jq
def test_production_is_not_touched_if_main_moved_on(steps) -> None:
    assert steps.run("deploy", "Require main to still be at this commit").returncode == 0
    steps.head(NEW_SHA)
    result = steps.run("deploy", "Require main to still be at this commit")
    assert result.returncode == 1
    assert "production was not changed" in errors(result)


@needs_jq
def test_the_deploy_job_needs_its_oidc_token(steps) -> None:
    result = steps.run(
        "deploy", "Check the deployment settings", {"ACTIONS_ID_TOKEN_REQUEST_TOKEN": ""}
    )
    assert result.returncode == 1
    assert "No OIDC token available" in errors(result)
    assert steps.run("deploy", "Check the deployment settings").returncode == 0


# --- verify-production ---------------------------------------------------------------------

PRODUCTION_STEP = "Verify production health, environment and version"


def healthy_production(steps: Steps, **overrides: tuple[int, Any]) -> None:
    answers = {
        "/api/health": (200, {"status": "ok"}),
        "/api/health/ready": (200, {"status": "ok"}),
        "/api/meta": meta("production", SHA),
        "/": (200, '<!doctype html><html><body><div id="root"></div></body></html>'),
    } | {path.replace("_", "/"): answer for path, answer in overrides.items()}
    for path, answer in answers.items():
        steps.answer(f"{PRODUCTION}{path}", answer)


@needs_jq
def test_production_reports_the_promoted_commit(steps) -> None:
    healthy_production(steps)
    result = steps.run("verify-production", PRODUCTION_STEP)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Promoted {SHA} from development to production" in steps.summary.read_text()
    for path in ("/api/health", "/api/health/ready", "/api/meta", "/"):
        assert steps.calls(f"{PRODUCTION}{path}") == 1


@needs_jq
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"_api_health": (502, "Bad Gateway")}, "/api/health is not ok"),
        (
            {"_api_health_ready": (503, {"status": "database unavailable"})},
            "/api/health/ready is not ok",
        ),
        ({"_api_meta": meta("development", SHA)}, "environment 'development', not production"),
        ({"_api_meta": meta("production", OLD_SHA)}, f"runs {OLD_SHA}, not the promoted {SHA}"),
        ({"_api_meta": meta("production", None)}, "runs an unknown version"),
        ({"_api_meta": (404, {"detail": "Not Found"})}, "/api/meta did not answer"),
        ({"_": (200, "<html>maintenance</html>")}, "does not serve the app"),
    ],
)
def test_promotion_fails_unless_production_runs_the_promoted_commit(
    steps, overrides, message
) -> None:
    healthy_production(steps, **overrides)
    result = steps.run("verify-production", PRODUCTION_STEP)
    assert result.returncode == 1
    assert message in errors(result)


def test_production_checks_retry_a_bounded_number_of_times(workflow) -> None:
    script = run_scripts(job(workflow, "verify-production"))
    assert "--max-time 10 --retry 12 --retry-delay 5 --retry-all-errors" in script


def test_scripts_are_valid_bash(workflow, tmp_path) -> None:
    for j in workflow["jobs"].values():
        for s in j["steps"]:
            path = tmp_path / "step.sh"
            path.write_text(s["run"])
            subprocess.run(["bash", "-n", str(path)], check=True)


def test_the_environment_variables_the_steps_use_are_defined(workflow) -> None:
    defined = set(workflow["env"]) | {
        "GITHUB_REPOSITORY",
        "GITHUB_EVENT_NAME",
        "GITHUB_REF",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_STEP_SUMMARY",
        "RUNNER_TEMP",
        "SECONDS",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    }
    for name, j in workflow["jobs"].items():
        local = defined | set(j.get("env", {}))
        for s in j["steps"]:
            script = s["run"]
            assigned = set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)=", script)) | set(
                re.findall(r"local ([a-z_]+)", script)
            )
            used = set(re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", script))
            missing = {v for v in used - local - assigned if v.isupper()}
            assert not missing, (name, s["name"], missing)
