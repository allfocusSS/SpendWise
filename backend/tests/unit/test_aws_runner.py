"""The self-hosted deploy runner's files (deploy/aws/runner): privilege and isolation guardrails.

Mode B of deploy/aws/README.md: the runner's user may run exactly one root command, the deploy
wrapper, for one commit SHA; its job hook refuses every job but deploy-aws on a push to main.
The scripts run here with stand-in files; nothing talks to GitHub or AWS.
"""

import re
import subprocess
from pathlib import Path

import pytest

RUNNER_DIR = Path(__file__).resolve().parents[3] / "deploy" / "aws" / "runner"
WRAPPER = RUNNER_DIR / "spendwise-deploy-sha"
HOOK = RUNNER_DIR / "job-started.sh"
SUDOERS = RUNNER_DIR / "spendwise-runner.sudoers"
INSTALLER = RUNNER_DIR / "install-runner.sh"

SHA = "835f9e36979e446878df74d9c9340bbd3ad46922"
REPOSITORY = "allfocusSS/SpendWise"
ACCEPTED_JOB = {
    "GITHUB_REPOSITORY": REPOSITORY,
    "GITHUB_EVENT_NAME": "push",
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/.github/workflows/ci.yml@refs/heads/main",
    "GITHUB_JOB": "deploy-aws",
    "GITHUB_SHA": SHA,
}


def run(script: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", **(env or {})},
        timeout=30,
    )


@pytest.mark.parametrize("script", [WRAPPER, HOOK, INSTALLER])
def test_scripts_are_valid_bash(script) -> None:
    subprocess.run(["bash", "-n", str(script)], check=True)


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["main"],
        ["refs/heads/main"],
        [SHA.upper()],
        [SHA[:39]],
        [SHA + "0"],
        [SHA[:7]],
        [SHA, SHA],
        [SHA + ";id"],
        [f"{SHA}\nid"],
        [" " + SHA],
        ["-h"],
        [""],
    ],
)
def test_wrapper_rejects_anything_but_one_40_character_lowercase_sha(args) -> None:
    result = run(WRAPPER, *args)
    assert result.returncode == 64, result.stderr
    assert "usage: spendwise-deploy-sha" in result.stderr


def test_wrapper_deploys_only_the_head_of_main_and_only_with_spendwise_deploy() -> None:
    text = WRAPPER.read_text()
    assert 'git ls-remote "https://github.com/$GITHUB_REPOSITORY.git" refs/heads/main' in text
    assert 'if [ "$head" != "$sha" ]; then' in text
    # The validated SHA is the only argument it ever passes on, to one fixed program.
    assert re.findall(r"^exec .*$", text, re.M) == ['exec /usr/local/bin/spendwise-deploy "$sha"']
    assert "eval" not in text


def test_sudo_allows_only_the_wrapper_with_a_sha() -> None:
    rules = [
        line
        for line in SUDOERS.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert rules == [
        "spendwise-runner ALL=(root) NOPASSWD: /usr/local/sbin/spendwise-deploy-sha ^[0-9a-f]{40}$"
    ]
    rule = rules[0]
    command = rule.split("NOPASSWD:", 1)[1]
    assert "ALL" not in command  # no general sudo
    for shell in ("/bin/bash", "/bin/sh", "/usr/bin/bash", "/usr/bin/env", "sudoedit"):
        assert shell not in command
    assert "," not in command  # exactly one command


@pytest.fixture
def hook(tmp_path: Path) -> Path:
    """The job hook, reading a stand-in for /etc/spendwise/deploy.env."""
    deploy_env = tmp_path / "deploy.env"
    deploy_env.write_text(f"GITHUB_REPOSITORY={REPOSITORY}\nGIT_REF=main\n")
    text = HOOK.read_text()
    assert text.count("/etc/spendwise/deploy.env") == 1
    copy = tmp_path / "job-started.sh"
    copy.write_text(text.replace("/etc/spendwise/deploy.env", str(deploy_env)))
    return copy


def test_hook_accepts_the_deploy_job_on_a_push_to_main(hook) -> None:
    result = run(hook, env=ACCEPTED_JOB)
    assert result.returncode == 0, result.stderr
    assert "accepted deploy-aws" in result.stdout


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("GITHUB_EVENT_NAME", "pull_request_target"),
        ("GITHUB_EVENT_NAME", "workflow_dispatch"),
        ("GITHUB_REF", "refs/pull/42/merge"),
        ("GITHUB_REF", "refs/heads/feature"),
        ("GITHUB_REF", "refs/tags/v1.0.0"),
        ("GITHUB_REPOSITORY", "someone/SpendWise"),
        ("GITHUB_WORKFLOW_REF", f"{REPOSITORY}/.github/workflows/evil.yml@refs/heads/main"),
        ("GITHUB_WORKFLOW_REF", f"{REPOSITORY}/.github/workflows/ci.yml@refs/pull/42/merge"),
        ("GITHUB_JOB", "backend"),
        ("GITHUB_JOB", "deploy-aws-oidc"),
    ],
)
def test_hook_refuses_every_other_job(hook, variable, value) -> None:
    result = run(hook, env=ACCEPTED_JOB | {variable: value})
    assert result.returncode != 0
    assert "refusing this job" in result.stderr


@pytest.mark.parametrize("missing", sorted(set(ACCEPTED_JOB) - {"GITHUB_SHA"}))
def test_hook_refuses_when_a_variable_is_missing(hook, missing) -> None:
    env = {k: v for k, v in ACCEPTED_JOB.items() if k != missing}
    assert run(hook, env=env).returncode != 0


def test_hook_fails_closed_without_the_deployment_settings(tmp_path) -> None:
    copy = tmp_path / "job-started.sh"
    copy.write_text(HOOK.read_text().replace("/etc/spendwise/deploy.env", str(tmp_path / "none")))
    assert run(copy, env=ACCEPTED_JOB).returncode != 0


def test_installer_gives_the_runner_user_no_route_to_root() -> None:
    text = INSTALLER.read_text()
    assert "--shell /sbin/nologin" in text
    assert "RUNNER_USER=spendwise-runner" in text
    # Never added to a group that grants root; removed from them if present.
    assert not re.search(r"usermod|useradd[^\n]*-G|gpasswd -a", text)
    assert "for group in docker wheel adm; do" in text
    # Root-owned wrapper and hook; the sudo rule only after visudo accepts it.
    assert "install -o root -g root -m 0755" in text
    assert 'visudo -cf "$here/spendwise-runner.sudoers"' in text
    assert "-m 0440" in text
    # The runner itself runs as that user, never as root.
    assert "RUNNER_ALLOW_RUNASROOT" not in text
    assert 'runuser -u "$RUNNER_USER" --' in text
    assert './svc.sh install "$RUNNER_USER"' in text


def test_installer_keeps_no_github_token() -> None:
    text = INSTALLER.read_text()
    assert 'read -rsp "Runner registration token' in text  # read from the terminal, not echoed
    assert "unset token" in text
    assert not re.search(r"\$token[^\n]*>", text)  # never written to a file
    assert "ghp_" not in text and "github_pat_" not in text


def test_installer_downloads_a_pinned_checksum_verified_runner() -> None:
    text = INSTALLER.read_text()
    assert re.search(r"^RUNNER_VERSION=\d+\.\d+\.\d+$", text, re.M)
    shas = re.findall(r"sha=([0-9a-f]+)", text)
    assert len(shas) == 2 and all(len(sha) == 64 for sha in shas)
    assert "sha256sum -c -" in text


def test_installer_registers_the_dedicated_label_and_the_job_hook() -> None:
    text = INSTALLER.read_text()
    assert "RUNNER_LABEL=spendwise-deploy" in text
    assert '--labels "$RUNNER_LABEL"' in text
    assert "--ephemeral" not in text
    assert 'echo "ACTIONS_RUNNER_HOOK_JOB_STARTED=$HOOK" >> .env' in text
    assert "HOOK=/usr/local/libexec/spendwise-runner-job-started" in text


def test_runner_user_cannot_reach_instance_metadata() -> None:
    unit = (RUNNER_DIR / "spendwise-runner-no-imds.service").read_text()
    rule = "-d 169.254.169.254/32 -m owner --uid-owner spendwise-runner -j REJECT"
    assert f"ExecStart=/usr/sbin/iptables -w -I OUTPUT {rule}" in unit
    assert f"ExecStop=/usr/sbin/iptables -w -D OUTPUT {rule}" in unit
    assert "WantedBy=multi-user.target" in unit
    text = INSTALLER.read_text()
    assert "systemctl enable spendwise-runner-no-imds.service" in text
    # The runner service requires the block, so it never runs without it.
    assert "Requires=spendwise-runner-no-imds.service" in text


def test_installer_verifies_isolation_before_starting_the_runner() -> None:
    text = INSTALLER.read_text()
    verify = text.index("if ! verify_isolation; then")
    assert verify < text.index("./svc.sh start")
    assert 'if [ "${1:-}" = --verify ]; then' in text  # repeatable on its own


@pytest.mark.parametrize(
    "check",
    [
        # Wrapper, hook and sudo rule: root:root, no group/other write bit, and neither the file
        # nor its directory writable by the runner user.
        'root_only "$WRAPPER"',
        'root_only "$HOOK"',
        'root_only "$SUDOERS"',
        '[ "$owner" = root:root ] && (((8#$mode & 8#022) == 0))',
        '! as_runner test -w "$1" && ! as_runner test -w "$(dirname "$1")"',
        # The sudo rule: mode 0440 and valid.
        '[ "$(stat -c %a "$SUDOERS" 2> /dev/null)" = 440 ] && visudo -cf "$SUDOERS"',
        # No root-equivalent groups, no other sudo.
        "for group in docker wheel adm; do",
        "as_runner sudo -n /usr/bin/true",
        # No database password, no Docker socket, no instance metadata.
        'as_runner test -r "$SECRETS" || as_runner cat "$SECRETS"',
        'for path in "$DOCKER_SOCKET" /run/docker.sock; do',
        'as_runner test -r "$path" || as_runner test -w "$path"',
        "iptables -w -C OUTPUT -d 169.254.169.254/32 -m owner",
    ],
)
def test_installer_isolation_checks(check) -> None:
    assert check in INSTALLER.read_text()


def test_installer_paths_are_the_ones_the_workflow_and_sudo_use() -> None:
    text = INSTALLER.read_text()
    assert "WRAPPER=/usr/local/sbin/spendwise-deploy-sha" in text
    assert "SUDOERS=/etc/sudoers.d/spendwise-runner" in text
    assert "SECRETS=/srv/spendwise/secrets/spendwise.env" in text
    assert "DOCKER_SOCKET=/var/run/docker.sock" in text
    assert 'install -o root -g root -m 0440 "$here/spendwise-runner.sudoers" "$SUDOERS"' in text
    assert 'visudo -cf "$SUDOERS"' in text
