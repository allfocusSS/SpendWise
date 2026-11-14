#!/bin/bash
# Installed root-owned as /usr/local/libexec/spendwise-runner-job-started by install-runner.sh,
# and set as the runner's ACTIONS_RUNNER_HOOK_JOB_STARTED. The runner runs it before every job;
# if it exits non-zero, the job fails before any of its steps run.
#
# The runner accepts only the deploy-aws job of ci.yml, for a push to main of this repository.
# A pull request (including one that edits the workflow to target this runner), another branch,
# another workflow or another job is refused before its code can run on the production host.
# GITHUB_* default variables are set by the runner from the job; a workflow cannot override them.
set -euo pipefail

# GITHUB_REPOSITORY (owner/name), written at first boot; root-owned.
# shellcheck source=/dev/null
expected_repository=$(. /etc/spendwise/deploy.env && echo "$GITHUB_REPOSITORY")

refuse() {
  echo "SpendWise deploy runner: refusing this job ($1)." >&2
  exit 1
}

[ "${GITHUB_REPOSITORY:-}" = "$expected_repository" ] || refuse "repository ${GITHUB_REPOSITORY:-unset}"
[ "${GITHUB_EVENT_NAME:-}" = push ] || refuse "event ${GITHUB_EVENT_NAME:-unset}"
[ "${GITHUB_REF:-}" = refs/heads/main ] || refuse "ref ${GITHUB_REF:-unset}"
[ "${GITHUB_WORKFLOW_REF:-}" = "$expected_repository/.github/workflows/ci.yml@refs/heads/main" ] ||
  refuse "workflow ${GITHUB_WORKFLOW_REF:-unset}"
[ "${GITHUB_JOB:-}" = deploy-aws ] || refuse "job ${GITHUB_JOB:-unset}"

echo "SpendWise deploy runner: accepted deploy-aws for ${GITHUB_SHA:-unknown commit}."
