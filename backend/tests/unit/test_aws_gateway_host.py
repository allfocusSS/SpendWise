"""The deploy gateway's host files (deploy/aws/gateway): privilege and isolation guardrails.

Mode B of deploy/aws/README.md: the gateway runs as spendwise-deploy-gateway, which may run
exactly one root command, the deploy wrapper, for one commit SHA. The scripts run here with
stand-in files; nothing talks to GitHub or AWS. The installer's checks themselves need a real
Amazon Linux host (deploy/aws/README.md, "Checking it by hand").
"""

import fcntl
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GATEWAY_DIR = ROOT / "deploy" / "aws" / "gateway"
WRAPPER = GATEWAY_DIR / "spendwise-deploy-sha"
SUDOERS = GATEWAY_DIR / "spendwise-deploy-gateway.sudoers"
INSTALLER = GATEWAY_DIR / "install-gateway.sh"
SERVICE = GATEWAY_DIR / "spendwise-deploy-gateway.service"
NO_IMDS = GATEWAY_DIR / "spendwise-deploy-gateway-no-imds.service"
TMPFILES = GATEWAY_DIR / "spendwise-deploy-gateway.tmpfiles.conf"
REQUIREMENTS = GATEWAY_DIR / "requirements.txt"

SHA = "835f9e36979e446878df74d9c9340bbd3ad46922"
USER = "spendwise-deploy-gateway"


def run(script: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", **(env or {})},
        timeout=30,
    )


@pytest.mark.parametrize("script", [WRAPPER, INSTALLER])
def test_scripts_are_valid_bash(script) -> None:
    subprocess.run(["bash", "-n", str(script)], check=True)


# --- The root wrapper ----------------------------------------------------------------------


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


def test_wrapper_locks_checks_the_head_of_main_then_runs_spendwise_deploy() -> None:
    text = WRAPPER.read_text()
    lock = text.index("exec 9> /run/spendwise-deploy.lock")
    assert text.index("if ! flock -n 9; then") > lock
    head = text.index('git ls-remote "https://github.com/$GITHUB_REPOSITORY.git" refs/heads/main')
    assert lock < head < text.index('if [ "$head" != "$sha" ]; then')
    # The validated SHA is the only argument it ever passes on, to one fixed program, with a
    # hard time limit.
    assert re.findall(r"^exec [^9].*$", text, re.M) == [
        'exec timeout --kill-after=60 3000 /usr/local/bin/spendwise-deploy "$sha"'
    ]
    # Its version for the app is that same validated SHA, set right before the deploy.
    assert re.findall(r"^export APP_VERSION=.*$", text, re.M) == ['export APP_VERSION="$sha"']
    assert text.index('export APP_VERSION="$sha"') > text.index('if [ "$head" != "$sha" ]; then')
    assert "eval" not in text
    assert "umask 022" in text  # sudo keeps the gateway's umask otherwise
    assert "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin" in text


@pytest.fixture
def wrapper_copy(tmp_path: Path) -> tuple[Path, Path]:
    """The wrapper with stand-ins for its lock, settings, git and spendwise-deploy."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").write_text(f'#!/bin/bash\necho "$(cat {tmp_path}/head)\trefs/heads/main"\n')
    deploy = tmp_path / "spendwise-deploy"
    deploy.write_text(
        f'#!/bin/bash\necho "Deploying $1 (${{1:0:7}})"\numask > {tmp_path}/umask\n'
        f'echo "$@" > {tmp_path}/args\necho "${{APP_VERSION-unset}}" > {tmp_path}/app_version\n'
    )
    for path in (bin_dir / "git", deploy):
        path.chmod(0o755)
    (tmp_path / "deploy.env").write_text("GITHUB_REPOSITORY=allfocusSS/SpendWise\n")
    lock = tmp_path / "deploy.lock"
    text = (
        WRAPPER.read_text()
        .replace("export PATH=", f"export PATH={bin_dir}:")
        .replace("/run/spendwise-deploy.lock", str(lock))
        .replace("/etc/spendwise/deploy.env", str(tmp_path / "deploy.env"))
        .replace("/usr/local/bin/spendwise-deploy", str(deploy))
    )
    copy = tmp_path / "spendwise-deploy-sha"
    copy.write_text(text)
    return copy, lock


needs_util_linux = pytest.mark.skipif(
    not (shutil.which("flock") and shutil.which("timeout")), reason="needs flock and timeout"
)


@needs_util_linux
def test_wrapper_deploys_the_head_of_main_with_a_normal_umask(wrapper_copy, tmp_path) -> None:
    copy, _ = wrapper_copy
    (tmp_path / "head").write_text(SHA)
    result = subprocess.run(
        ["bash", "-c", f'umask 077; exec bash "{copy}" {SHA}'], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f"Deploying {SHA} ")
    assert (tmp_path / "args").read_text() == SHA + "\n"
    assert (tmp_path / "umask").read_text().strip() == "0022"
    # The app container gets the same SHA as its version (compose.yaml: APP_VERSION).
    assert (tmp_path / "app_version").read_text() == SHA + "\n"


@needs_util_linux
def test_wrapper_version_is_the_deployed_sha_whatever_the_caller_set(
    wrapper_copy, tmp_path
) -> None:
    copy, _ = wrapper_copy
    (tmp_path / "head").write_text(SHA)
    result = run(copy, SHA, env={"APP_VERSION": "1" * 40})
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "app_version").read_text() == SHA + "\n"


@needs_util_linux
def test_wrapper_refuses_a_commit_that_is_not_the_head_of_main(wrapper_copy, tmp_path) -> None:
    copy, _ = wrapper_copy
    (tmp_path / "head").write_text("1" * 40)
    result = run(copy, SHA)
    assert result.returncode == 65
    assert "not the head of main" in result.stderr
    assert not (tmp_path / "args").exists()


@needs_util_linux
def test_wrapper_refuses_while_another_deploy_holds_the_lock(wrapper_copy, tmp_path) -> None:
    copy, lock = wrapper_copy
    (tmp_path / "head").write_text(SHA)
    with lock.open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        result = run(copy, SHA)
    assert result.returncode == 75
    assert "Another deploy is running" in result.stderr
    assert not (tmp_path / "args").exists()
    assert run(copy, SHA).returncode == 0  # free again


# --- sudo ----------------------------------------------------------------------------------


def test_sudo_allows_only_the_wrapper_with_a_sha() -> None:
    rules = [
        line
        for line in SUDOERS.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert rules == [
        f"{USER} ALL=(root) NOPASSWD: /usr/local/sbin/spendwise-deploy-sha ^[0-9a-f]{{40}}$"
    ]
    command = rules[0].split("NOPASSWD:", 1)[1]
    assert "ALL" not in command  # no general sudo
    for shell in ("/bin/bash", "/bin/sh", "/usr/bin/bash", "/usr/bin/env", "sudoedit"):
        assert shell not in command
    assert "," not in command  # exactly one command


# --- The installer -------------------------------------------------------------------------


def test_installer_creates_a_locked_down_user() -> None:
    text = INSTALLER.read_text()
    assert f"GATEWAY_USER={USER}" in text
    useradd = "useradd --system --no-create-home --home-dir /nonexistent --shell /sbin/nologin"
    assert f'{useradd} "$GATEWAY_USER"' in text
    # Never added to a group that grants root; removed from them if present.
    assert not re.search(r"usermod|useradd[^\n]*-G|gpasswd -a", text)
    assert text.count("for group in docker wheel adm; do") == 2


def test_installer_installs_everything_root_owned() -> None:
    text = INSTALLER.read_text()
    for source, target in [
        ("spendwise_deploy_gateway.py", "$APP"),
        ("spendwise-deploy-sha", "$WRAPPER"),
    ]:
        assert re.search(
            rf'install -o root -g root -m 0[67][45][45] "\$here/{source}" "{re.escape(target)}"',
            text,
        )
    assert (
        'install -o root -g root -m 0440 "$here/spendwise-deploy-gateway.sudoers" "$SUDOERS"'
        in text
    )
    assert 'visudo -cf "$here/spendwise-deploy-gateway.sudoers"' in text
    assert 'visudo -cf "$SUDOERS"' in text
    assert 'chown -R root:root "$PREFIX"' in text
    for path in ("$CONFIG", "$IMDS_UNIT", "$TMPFILES", "$UNIT"):
        assert re.search(rf'install -o root -g root -m 0644 "[^"]+" "{re.escape(path)}"', text), (
            path
        )


def test_installer_installs_only_hash_pinned_wheels() -> None:
    text = INSTALLER.read_text()
    assert "--require-hashes --only-binary :all: --no-deps -r" in text
    requirements = [
        line for line in REQUIREMENTS.read_text().splitlines() if line and line[0].isalpha()
    ]
    names = {re.match(r"([a-z0-9-]+)==", line).group(1) for line in requirements}
    assert names == {"cffi", "cryptography", "pycparser", "pyjwt"}
    entries = re.split(r"\n(?=[a-z])", REQUIREMENTS.read_text().split("\n", 7)[7])
    assert len(entries) == 4
    for entry in entries:
        assert re.search(r"--hash=sha256:[0-9a-f]{64}", entry), entry.split()[0]


def test_installer_needs_no_token_or_secret() -> None:
    text = INSTALLER.read_text()
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    for forbidden in ("token", "TOKEN", "ghp_", "github_pat_", "AWS_ACCESS_KEY", "read -s"):
        assert forbidden not in code
    assert "RUNNER" not in text and "actions-runner" not in text


@pytest.mark.parametrize(
    "check",
    [
        # The user itself: not root, no shell, no password, no root-equivalent group.
        '[[ $(cut -d: -f7 <<< "$entry") == */nologin ]]',
        '[[ $(getent shadow "$GATEWAY_USER" | cut -d: -f2) =~ ^[!*] ]]',
        "for group in docker wheel adm; do",
        'grep -qx "User=$GATEWAY_USER" "$UNIT"',
        # Everything it runs or reads, and what runs as root for it: root:root, no group/other
        # write bit, and neither the file nor its directory writable by the gateway user.
        '"$APP" "$CONFIG" "$UNIT" "$IMDS_UNIT" "$TMPFILES" "$WRAPPER" "$SUDOERS"',
        '"$DEPLOY" "$DEPLOY_ENV"; do',
        '[ "$owner" = root:root ] && (((8#$mode & 8#022) == 0))',
        '! as_gateway test -w "$1" && ! as_gateway test -w "$(dirname "$1")"',
        'find "$PREFIX" ! -type l \\( ! -user root -o -perm /022 \\)',
        # The sudo rule: mode 0440, valid, the wrapper with a SHA only, and nobody else's.
        '[ "$(stat -c %a "$SUDOERS" 2> /dev/null)" = 440 ] && visudo -cf "$SUDOERS"',
        'as_gateway sudo -n -l "$WRAPPER" "$SHA_EXAMPLE"',
        'as_gateway sudo -n -l "$WRAPPER" main',
        'as_gateway sudo -n -l "$WRAPPER" "$SHA_EXAMPLE" extra',
        "as_gateway sudo -n -l /usr/bin/true",
        "as_gateway sudo -n -l /bin/bash",
        'grep -rlsF "$WRAPPER" /etc/sudoers /etc/sudoers.d | grep -vqx "$SUDOERS"',
        # No database password, no Docker or containerd socket, no instance metadata.
        'as_gateway test -r "$SECRETS" || as_gateway cat "$SECRETS"',
        'for path in "$DOCKER_SOCKET" /run/docker.sock /run/containerd/containerd.sock; do',
        'as_gateway test -r "$path" || as_gateway test -w "$path"',
        "iptables -w -C OUTPUT -d 169.254.169.254/32 -m owner",
        '[ "$(stat -c %U:%a "$SOCKET_DIR" 2> /dev/null)" = "$GATEWAY_USER:750" ]',
    ],
)
def test_installer_isolation_checks(check) -> None:
    text = INSTALLER.read_text()
    verify = text[text.index("verify_isolation() {") : text.index('if [ "${1:-}" = --verify ]')]
    assert check in verify


def test_installer_verifies_isolation_before_starting_the_gateway() -> None:
    text = INSTALLER.read_text()
    verify = text.index("if ! verify_isolation; then")
    assert verify < text.index("systemctl restart spendwise-deploy-gateway.service")
    assert "systemctl disable --now spendwise-deploy-gateway.service" in text[verify:]
    assert 'if [ "${1:-}" = --verify ]; then' in text  # repeatable on its own
    # A restart would stop a running deploy, so it waits for the deploy lock to be free.
    assert 'if [ -e "$LOCK" ] && ! flock -n "$LOCK" true; then' in text


def test_installer_paths_match_the_other_files() -> None:
    text = INSTALLER.read_text()
    assert "WRAPPER=/usr/local/sbin/spendwise-deploy-sha" in text
    assert "SUDOERS=/etc/sudoers.d/spendwise-deploy-gateway" in text
    assert "SECRETS=/srv/spendwise/secrets/spendwise.env" in text
    assert "DOCKER_SOCKET=/var/run/docker.sock" in text
    assert "SOCKET_DIR=/run/spendwise-deploy-gateway" in text
    assert (
        "LOCK=/run/spendwise-deploy.lock" in text
        and "/run/spendwise-deploy.lock" in WRAPPER.read_text()
    )
    assert (
        'echo "DEPLOY_GATEWAY_HEALTH_URL=https://$SPENDWISE_SITE_ADDRESS/api/health/ready"' in text
    )


# --- systemd and tmpfiles ------------------------------------------------------------------


def test_gateway_service_runs_unprivileged_and_only_with_the_metadata_block() -> None:
    unit = SERVICE.read_text()
    assert f"User={USER}\n" in unit and f"Group={USER}\n" in unit
    assert "User=root" not in unit
    assert "Requires=spendwise-deploy-gateway-no-imds.service" in unit
    assert "After=spendwise-deploy-gateway-no-imds.service" in unit
    assert (
        "ExecStart=/usr/local/lib/spendwise-deploy-gateway/venv/bin/python -I "
        "/usr/local/lib/spendwise-deploy-gateway/spendwise_deploy_gateway.py\n"
    ) in unit
    assert "EnvironmentFile=/etc/spendwise/deploy-gateway.env" in unit
    assert "StateDirectoryMode=0700" in unit
    # No listening port of any kind: the socket path comes from the settings.
    assert "ListenStream" not in unit and "ListenDatagram" not in unit
    # NoNewPrivileges would break sudo; the reason is documented in the unit.
    assert not re.search(r"^NoNewPrivileges=", unit, re.M)
    assert "NoNewPrivileges=" in unit


def test_gateway_user_cannot_reach_instance_metadata() -> None:
    unit = NO_IMDS.read_text()
    rule = f"-d 169.254.169.254/32 -m owner --uid-owner {USER} -j REJECT"
    assert f"ExecStart=/usr/sbin/iptables -w -I OUTPUT {rule}" in unit
    assert f"ExecStop=/usr/sbin/iptables -w -D OUTPUT {rule}" in unit
    assert "WantedBy=multi-user.target" in unit


def test_socket_directory_is_private_to_the_gateway_and_root() -> None:
    lines = [ln for ln in TMPFILES.read_text().splitlines() if ln and not ln.startswith("#")]
    assert lines == [f"d /run/spendwise-deploy-gateway 0750 {USER} {USER} -"]


def test_the_abandoned_self_hosted_runner_is_gone() -> None:
    assert not (ROOT / "deploy" / "aws" / "runner").exists()
    assert not (ROOT / ".github" / "actionlint.yaml").exists()
    for path in GATEWAY_DIR.iterdir():
        if path.is_file() and path.suffix != ".txt":
            assert "spendwise-runner" not in path.read_text(), path.name
