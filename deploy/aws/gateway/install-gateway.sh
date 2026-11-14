#!/bin/bash
# Install (or reinstall) the SpendWise deploy gateway on the EC2 instance (deploy/aws/README.md,
# "Mode B: GitHub OIDC deploy gateway"). Run as root from a Session Manager shell, from the
# root-owned checkout that spendwise-deploy maintains:
#
#   sudo bash /opt/spendwise/src/deploy/aws/gateway/install-gateway.sh
#
# It needs no token, key or secret: the gateway trusts GitHub's published OIDC signing keys.
# Running it again is safe; it reinstalls every file. Before (re)starting the gateway it checks
# the gateway user's isolation, and refuses to start it if a check fails. To repeat only those
# checks later:
#
#   sudo bash /opt/spendwise/src/deploy/aws/gateway/install-gateway.sh --verify
set -euo pipefail

GATEWAY_USER=spendwise-deploy-gateway
PYTHON=python3.13
PREFIX=/usr/local/lib/spendwise-deploy-gateway
APP=$PREFIX/spendwise_deploy_gateway.py
VENV=$PREFIX/venv
CONFIG=/etc/spendwise/deploy-gateway.env
UNIT=/etc/systemd/system/spendwise-deploy-gateway.service
IMDS_UNIT=/etc/systemd/system/spendwise-deploy-gateway-no-imds.service
TMPFILES=/etc/tmpfiles.d/spendwise-deploy-gateway.conf
SOCKET_DIR=/run/spendwise-deploy-gateway
WRAPPER=/usr/local/sbin/spendwise-deploy-sha
SUDOERS=/etc/sudoers.d/spendwise-deploy-gateway
DEPLOY=/usr/local/bin/spendwise-deploy
DEPLOY_ENV=/etc/spendwise/deploy.env
SECRETS=/srv/spendwise/secrets/spendwise.env
DOCKER_SOCKET=/var/run/docker.sock
LOCK=/run/spendwise-deploy.lock
SHA_EXAMPLE=0123456789abcdef0123456789abcdef01234567
here=$(cd "$(dirname "$0")" && pwd)

if [ "$(id -u)" -ne 0 ]; then echo "Run as root (sudo bash $0)."; exit 1; fi

# Every check runs; the function fails if any of them did.
verify_isolation() {
  local failures=0 path entry
  ok() { echo "  ok    $1"; }
  bad() { echo "  FAIL  $1"; failures=$((failures + 1)); }
  as_gateway() { runuser -u "$GATEWAY_USER" -- "$@" 2> /dev/null; }
  # root:root, no group or other write bit, and the gateway user can write neither the file nor
  # the directory it is in (so it cannot replace it either).
  root_only() {
    local owner mode
    owner=$(stat -c %U:%G "$1" 2> /dev/null || echo missing)
    mode=$(stat -c %a "$1" 2> /dev/null || echo 0)
    if [ "$owner" = root:root ] && (((8#$mode & 8#022) == 0)) &&
      ! as_gateway test -w "$1" && ! as_gateway test -w "$(dirname "$1")"; then
      ok "$1 is $owner, mode $mode, not writable by $GATEWAY_USER"
    else
      bad "$1 must be root:root and not writable by $GATEWAY_USER (is $owner, mode $mode)"
    fi
  }

  echo "== Isolation of $GATEWAY_USER"
  if ! entry=$(getent passwd "$GATEWAY_USER"); then
    bad "user $GATEWAY_USER does not exist"
    return 1
  fi
  if [ "$(id -u "$GATEWAY_USER")" -ne 0 ] && [[ $(cut -d: -f7 <<< "$entry") == */nologin ]]; then
    ok "$GATEWAY_USER is not root and has no login shell"
  else
    bad "$GATEWAY_USER must not be root and must have a nologin shell"
  fi
  if [[ $(getent shadow "$GATEWAY_USER" | cut -d: -f2) =~ ^[!*] ]]; then
    ok "$GATEWAY_USER has no password"
  else
    bad "$GATEWAY_USER has a password"
  fi
  for group in docker wheel adm; do
    if id -nG "$GATEWAY_USER" | tr ' ' '\n' | grep -qx "$group"; then
      bad "$GATEWAY_USER is in the $group group"
    else
      ok "$GATEWAY_USER is not in the $group group"
    fi
  done
  if grep -qx "User=$GATEWAY_USER" "$UNIT" 2> /dev/null; then
    ok "the gateway service runs as $GATEWAY_USER"
  else
    bad "$UNIT does not run the gateway as $GATEWAY_USER"
  fi

  # Everything the gateway runs, reads as configuration, or that runs as root on its behalf.
  for path in "$APP" "$CONFIG" "$UNIT" "$IMDS_UNIT" "$TMPFILES" "$WRAPPER" "$SUDOERS" \
    "$DEPLOY" "$DEPLOY_ENV"; do
    root_only "$path"
  done
  if [ -d "$VENV" ] && [ -z "$(find "$PREFIX" ! -type l \( ! -user root -o -perm /022 \) -print -quit)" ]; then
    ok "$PREFIX (program and virtual environment) is root-owned and not group/other-writable"
  else
    bad "$PREFIX must exist, be root-owned and not group/other-writable"
  fi

  if [ "$(stat -c %a "$SUDOERS" 2> /dev/null)" = 440 ] && visudo -cf "$SUDOERS" > /dev/null; then
    ok "$SUDOERS is mode 0440 and valid (visudo -cf)"
  else
    bad "$SUDOERS must be mode 0440 and pass visudo -cf"
  fi
  if as_gateway sudo -n -l "$WRAPPER" "$SHA_EXAMPLE" > /dev/null; then
    ok "$GATEWAY_USER may run $WRAPPER with a commit SHA"
  else
    bad "$GATEWAY_USER cannot run $WRAPPER with a commit SHA"
  fi
  if as_gateway sudo -n -l "$WRAPPER" main > /dev/null ||
    as_gateway sudo -n -l "$WRAPPER" "$SHA_EXAMPLE" extra > /dev/null ||
    as_gateway sudo -n -l /usr/bin/true > /dev/null ||
    as_gateway sudo -n -l /bin/bash > /dev/null; then
    bad "$GATEWAY_USER can run other commands or arguments with sudo"
  else
    ok "$GATEWAY_USER cannot run anything else with sudo"
  fi
  # The old self-hosted runner's rule (deploy/aws/README.md, "Cleaning up the abandoned runner"),
  # or any other rule, must not grant the wrapper to someone else.
  if grep -rlsF "$WRAPPER" /etc/sudoers /etc/sudoers.d | grep -vqx "$SUDOERS"; then
    bad "another sudo rule mentions $WRAPPER: $(grep -rlsF "$WRAPPER" /etc/sudoers /etc/sudoers.d | grep -vx "$SUDOERS" | tr '\n' ' ')"
  else
    ok "no other sudo rule mentions $WRAPPER"
  fi

  if [ ! -e "$SECRETS" ]; then
    bad "$SECRETS is missing, so it cannot be checked"
  elif as_gateway test -r "$SECRETS" || as_gateway cat "$SECRETS" > /dev/null; then
    bad "$GATEWAY_USER can read $SECRETS"
  else
    ok "$GATEWAY_USER cannot read $SECRETS"
  fi
  # Docker (and containerd) access is root access.
  for path in "$DOCKER_SOCKET" /run/docker.sock /run/containerd/containerd.sock; do
    if [ -e "$path" ] && { as_gateway test -r "$path" || as_gateway test -w "$path"; }; then
      bad "$GATEWAY_USER can access $path"
    else
      ok "$GATEWAY_USER cannot access $path"
    fi
  done
  if iptables -w -C OUTPUT -d 169.254.169.254/32 -m owner --uid-owner "$GATEWAY_USER" -j REJECT 2> /dev/null; then
    ok "$GATEWAY_USER cannot reach the instance metadata service"
  else
    bad "the instance metadata block for $GATEWAY_USER is not in place"
  fi
  if [ "$(stat -c %U:%a "$SOCKET_DIR" 2> /dev/null)" = "$GATEWAY_USER:750" ]; then
    ok "$SOCKET_DIR is $GATEWAY_USER, mode 0750"
  else
    bad "$SOCKET_DIR must be owned by $GATEWAY_USER with mode 0750"
  fi

  [ "$failures" -eq 0 ]
}

if [ "${1:-}" = --verify ]; then
  verify_isolation
  exit
fi
if [ ! -x "$DEPLOY" ]; then
  echo "$DEPLOY is missing: this is not the SpendWise instance."
  exit 1
fi
# GITHUB_REPOSITORY (owner/name) and SPENDWISE_SITE_ADDRESS, written at first boot.
# shellcheck source=/dev/null
. "$DEPLOY_ENV"
if ! grep -qx "DEPLOY_GATEWAY_REPOSITORY=$GITHUB_REPOSITORY" "$here/deploy-gateway.env"; then
  echo "deploy-gateway.env is for another repository than $GITHUB_REPOSITORY ($DEPLOY_ENV)."
  exit 1
fi
# A gateway restart would stop a running deploy (it runs inside the gateway's unit).
if [ -e "$LOCK" ] && ! flock -n "$LOCK" true; then
  echo "A deploy is running; run this again when it has finished."
  exit 1
fi

echo "== Packages: Python $PYTHON and iptables"
dnf install -y "$PYTHON" "$PYTHON-pip" iptables-nft

echo "== The gateway's user: no password, no login shell, no group that grants root"
if ! id "$GATEWAY_USER" > /dev/null 2>&1; then
  useradd --system --no-create-home --home-dir /nonexistent --shell /sbin/nologin "$GATEWAY_USER"
fi
for group in docker wheel adm; do
  if id -nG "$GATEWAY_USER" | tr ' ' '\n' | grep -qx "$group"; then
    gpasswd -d "$GATEWAY_USER" "$group"
  fi
done

echo "== Program and its pinned dependencies (root-owned)"
install -d -o root -g root -m 0755 "$PREFIX"
install -o root -g root -m 0644 "$here/spendwise_deploy_gateway.py" "$APP"
if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 13))'; then
  rm -rf "$VENV"
  "$PYTHON" -m venv "$VENV"
fi
# Only the exact files listed (by hash) in requirements.txt, and only prebuilt wheels.
"$VENV/bin/pip" install --quiet --disable-pip-version-check --no-cache-dir \
  --require-hashes --only-binary :all: --no-deps -r "$here/requirements.txt"
chown -R root:root "$PREFIX"
chmod -R go-w "$PREFIX"

echo "== Settings (root-owned, nothing secret)"
{
  cat "$here/deploy-gateway.env"
  echo "DEPLOY_GATEWAY_HEALTH_URL=https://$SPENDWISE_SITE_ADDRESS/api/health/ready"
} > "$CONFIG.new"
install -o root -g root -m 0644 "$CONFIG.new" "$CONFIG"
rm -f "$CONFIG.new"

echo "== Deploy wrapper and sudo rule (root:root, not writable by $GATEWAY_USER)"
install -o root -g root -m 0755 "$here/spendwise-deploy-sha" "$WRAPPER"
visudo -cf "$here/spendwise-deploy-gateway.sudoers"
install -o root -g root -m 0440 "$here/spendwise-deploy-gateway.sudoers" "$SUDOERS"
visudo -cf "$SUDOERS"
visudo -c

echo "== No instance metadata (and so no instance role credentials) for $GATEWAY_USER"
install -o root -g root -m 0644 "$here/spendwise-deploy-gateway-no-imds.service" "$IMDS_UNIT"

echo "== Socket directory and service"
install -o root -g root -m 0644 "$here/spendwise-deploy-gateway.tmpfiles.conf" "$TMPFILES"
systemd-tmpfiles --create "$TMPFILES"
install -o root -g root -m 0644 "$here/spendwise-deploy-gateway.service" "$UNIT"
systemctl daemon-reload
systemctl enable spendwise-deploy-gateway-no-imds.service spendwise-deploy-gateway.service
systemctl restart spendwise-deploy-gateway-no-imds.service

# Nothing starts unless every isolation check passes.
if ! verify_isolation; then
  systemctl disable --now spendwise-deploy-gateway.service || true
  echo "Isolation checks failed; the gateway was not started."
  exit 1
fi

echo "== Settings and GitHub's signing keys, as $GATEWAY_USER"
# shellcheck disable=SC2016 # $1..$3 are expanded by the inner shell, from the arguments after _
runuser -u "$GATEWAY_USER" -- env -i PATH=/usr/bin:/usr/sbin STATE_DIRECTORY=/nonexistent \
  bash -c 'set -a; . "$1"; set +a; exec "$2" -I "$3" --check' _ "$CONFIG" "$VENV/bin/python" "$APP"

systemctl restart spendwise-deploy-gateway.service
for _ in $(seq 1 20); do
  [ -S "$SOCKET_DIR/gateway.sock" ] && break
  sleep 1
done
systemctl --no-pager status spendwise-deploy-gateway.service | head -n 5 || true
if [ ! -S "$SOCKET_DIR/gateway.sock" ]; then
  echo "The gateway did not open $SOCKET_DIR/gateway.sock (journalctl -u spendwise-deploy-gateway)."
  exit 1
fi

echo "== What $GATEWAY_USER may run as root"
sudo -l -U "$GATEWAY_USER"
echo "Done. Caddy forwards POST https://$SPENDWISE_SITE_ADDRESS/_deploy to the gateway once it"
echo "runs with the bind mount in deploy/aws/compose.aws.yaml (any deploy of this commit or later)."
