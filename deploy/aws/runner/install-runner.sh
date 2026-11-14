#!/bin/bash
# One-time bootstrap of the SpendWise deploy runner on the EC2 instance (deploy/aws/README.md,
# "Mode B: self-hosted deploy runner"). Run as root from a Session Manager shell, from the
# root-owned checkout that spendwise-deploy maintains:
#
#   sudo bash /opt/spendwise/src/deploy/aws/runner/install-runner.sh
#
# It asks for a runner registration token (valid for one hour, created with
#   gh api -X POST repos/OWNER/REPO/actions/runners/registration-token --jq .token
# on your machine), uses it once to register, and keeps no copy. Running it again is safe: it
# reinstalls the wrapper, hook and sudo rule, and skips what is already done.
#
# Before starting the runner it checks the runner user's isolation, and refuses to start it if a
# check fails. To repeat only those checks later:
#
#   sudo bash /opt/spendwise/src/deploy/aws/runner/install-runner.sh --verify
set -euo pipefail

RUNNER_VERSION=2.338.2
RUNNER_USER=spendwise-runner
RUNNER_DIR=/opt/actions-runner
RUNNER_NAME=spendwise-ec2
RUNNER_LABEL=spendwise-deploy # plus the default labels self-hosted, Linux and X64/ARM64
HOOK=/usr/local/libexec/spendwise-runner-job-started
WRAPPER=/usr/local/sbin/spendwise-deploy-sha
SUDOERS=/etc/sudoers.d/spendwise-runner
SECRETS=/srv/spendwise/secrets/spendwise.env
DOCKER_SOCKET=/var/run/docker.sock
here=$(cd "$(dirname "$0")" && pwd)

if [ "$(id -u)" -ne 0 ]; then echo "Run as root (sudo bash $0)."; exit 1; fi

# Every check runs; the function fails if any of them did.
verify_isolation() {
  local failures=0 path
  ok() { echo "  ok    $1"; }
  bad() { echo "  FAIL  $1"; failures=$((failures + 1)); }
  as_runner() { runuser -u "$RUNNER_USER" -- "$@" 2> /dev/null; }
  # root:root, no group or other write bit, and the runner user can write neither the file nor
  # the directory it is in (so it cannot replace it either).
  root_only() {
    local owner mode
    owner=$(stat -c %U:%G "$1" 2> /dev/null || echo missing)
    mode=$(stat -c %a "$1" 2> /dev/null || echo 0)
    if [ "$owner" = root:root ] && (((8#$mode & 8#022) == 0)) &&
      ! as_runner test -w "$1" && ! as_runner test -w "$(dirname "$1")"; then
      ok "$1 is $owner, mode $mode, not writable by $RUNNER_USER"
    else
      bad "$1 must be root:root and not writable by $RUNNER_USER (is $owner, mode $mode)"
    fi
  }

  echo "== Isolation of $RUNNER_USER"
  if ! id "$RUNNER_USER" > /dev/null 2>&1; then
    bad "user $RUNNER_USER does not exist"
    return 1
  fi
  root_only "$WRAPPER"
  root_only "$HOOK"
  root_only "$SUDOERS"
  if [ "$(stat -c %a "$SUDOERS" 2> /dev/null)" = 440 ] && visudo -cf "$SUDOERS" > /dev/null; then
    ok "$SUDOERS is mode 0440 and valid (visudo -cf)"
  else
    bad "$SUDOERS must be mode 0440 and pass visudo -cf"
  fi
  for group in docker wheel adm; do
    if id -nG "$RUNNER_USER" | tr ' ' '\n' | grep -qx "$group"; then
      bad "$RUNNER_USER is in the $group group"
    else
      ok "$RUNNER_USER is not in the $group group"
    fi
  done
  if as_runner sudo -n /usr/bin/true; then
    bad "$RUNNER_USER can run other commands with sudo"
  else
    ok "$RUNNER_USER cannot run other commands with sudo"
  fi
  if [ ! -e "$SECRETS" ]; then
    bad "$SECRETS is missing, so it cannot be checked"
  elif as_runner test -r "$SECRETS" || as_runner cat "$SECRETS" > /dev/null; then
    bad "$RUNNER_USER can read $SECRETS"
  else
    ok "$RUNNER_USER cannot read $SECRETS"
  fi
  for path in "$DOCKER_SOCKET" /run/docker.sock; do
    if [ -e "$path" ] && { as_runner test -r "$path" || as_runner test -w "$path"; }; then
      bad "$RUNNER_USER can access $path (Docker access is root access)"
    else
      ok "$RUNNER_USER cannot access $path"
    fi
  done
  if iptables -w -C OUTPUT -d 169.254.169.254/32 -m owner --uid-owner "$RUNNER_USER" -j REJECT 2> /dev/null; then
    ok "$RUNNER_USER cannot reach the instance metadata service"
  else
    bad "the instance metadata block for $RUNNER_USER is not in place"
  fi

  [ "$failures" -eq 0 ]
}

# Registers the runner from the current directory (the runner's). The registration token is an
# opaque GitHub value: it must not be empty, and is otherwise passed unchanged to the runner's own
# config.sh, which checks with GitHub whether it is valid and unexpired. It is never echoed,
# logged or written to a file, and is gone when the function returns.
register_runner() {
  local token
  read -rsp "Runner registration token (not echoed): " token
  echo
  if [ -z "$token" ]; then
    echo "No registration token given."
    return 1
  fi
  runuser -u "$RUNNER_USER" -- env HOME="/home/$RUNNER_USER" ./config.sh --unattended \
    --url "https://github.com/$GITHUB_REPOSITORY" --token "$token" \
    --name "$RUNNER_NAME" --labels "$RUNNER_LABEL" --work _work --replace
}

if [ "${1:-}" = --verify ]; then
  verify_isolation
  exit
fi
if [ ! -x /usr/local/bin/spendwise-deploy ]; then
  echo "/usr/local/bin/spendwise-deploy is missing: this is not the SpendWise instance."
  exit 1
fi
# GITHUB_REPOSITORY (owner/name), written at first boot.
# shellcheck source=/dev/null
. /etc/spendwise/deploy.env

# Official release tarballs, pinned and checksum-verified (the release's published SHA-256).
case "$(uname -m)" in
  x86_64) arch=x64 sha=baebf204307bac6193480852732f0aba2ae97b6c5597c244f4d5558390147c40 ;;
  aarch64) arch=arm64 sha=670adb2f268fe21dcbb58b3db0e0aa9d5b3bddfe2c651481336e561ff86de945 ;;
  *) echo "Unsupported architecture: $(uname -m)"; exit 1 ;;
esac

echo "== Packages the runner needs"
dnf install -y libicu tar gzip iptables-nft

echo "== The runner's user: no password, no login shell, no group that grants root"
if ! id "$RUNNER_USER" > /dev/null 2>&1; then
  useradd --system --create-home --home-dir "/home/$RUNNER_USER" --shell /sbin/nologin "$RUNNER_USER"
fi
for group in docker wheel adm; do
  if id -nG "$RUNNER_USER" | tr ' ' '\n' | grep -qx "$group"; then
    gpasswd -d "$RUNNER_USER" "$group"
  fi
done

echo "== Deploy wrapper, job hook and sudo rule (root:root, not writable by $RUNNER_USER)"
install -o root -g root -m 0755 "$here/spendwise-deploy-sha" "$WRAPPER"
install -d -o root -g root -m 0755 "$(dirname "$HOOK")"
install -o root -g root -m 0755 "$here/job-started.sh" "$HOOK"
visudo -cf "$here/spendwise-runner.sudoers"
install -o root -g root -m 0440 "$here/spendwise-runner.sudoers" "$SUDOERS"
visudo -cf "$SUDOERS"
visudo -c

echo "== No instance metadata (and so no instance role credentials) for $RUNNER_USER"
install -o root -g root -m 0644 "$here/spendwise-runner-no-imds.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable spendwise-runner-no-imds.service
systemctl restart spendwise-runner-no-imds.service

echo "== GitHub Actions runner $RUNNER_VERSION ($arch)"
if [ ! -x "$RUNNER_DIR/config.sh" ]; then
  tarball=$(mktemp)
  trap 'rm -f "$tarball"' EXIT
  curl -fsSL -o "$tarball" \
    "https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/actions-runner-linux-$arch-$RUNNER_VERSION.tar.gz"
  echo "$sha  $tarball" | sha256sum -c -
  install -d -m 0750 "$RUNNER_DIR"
  tar -xzf "$tarball" -C "$RUNNER_DIR"
  # The runner updates itself in place, so its own directory belongs to its user.
  chown -R "$RUNNER_USER:$RUNNER_USER" "$RUNNER_DIR"
fi
cd "$RUNNER_DIR"

echo "== Registration with https://github.com/$GITHUB_REPOSITORY"
if [ ! -f .runner ]; then
  register_runner
fi

echo "== Job hook: refuse every job except deploy-aws on a push to main"
touch .env
sed -i '/^ACTIONS_RUNNER_HOOK_JOB_STARTED=/d' .env
echo "ACTIONS_RUNNER_HOOK_JOB_STARTED=$HOOK" >> .env
chown "$RUNNER_USER:$RUNNER_USER" .env

# Nothing starts unless every isolation check passes.
if ! verify_isolation; then
  echo "Isolation checks failed; the runner was not started."
  exit 1
fi

echo "== Service (systemd, runs as $RUNNER_USER)"
if [ ! -f .service ]; then
  ./svc.sh install "$RUNNER_USER"
fi
# The runner starts only after its user is cut off from the metadata service.
unit=$(cat .service)
mkdir -p "/etc/systemd/system/$unit.d"
printf '[Unit]\nRequires=spendwise-runner-no-imds.service\nAfter=spendwise-runner-no-imds.service\n' \
  > "/etc/systemd/system/$unit.d/spendwise.conf"
systemctl daemon-reload
./svc.sh stop > /dev/null 2>&1 || true
./svc.sh start
./svc.sh status --no-pager | head -n 5 || true

echo "== What $RUNNER_USER may run as root"
sudo -l -U "$RUNNER_USER"
echo "Done. The runner appears in the repository under Settings, Actions, Runners."
