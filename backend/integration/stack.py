"""Drive the real Docker Compose stack (compose.yaml) for the integration and end-to-end tests.

The integration tests (backend/integration) use the Stack class directly. Other runners, such as
the Playwright suite in frontend/e2e, use the same logic through the command line:

  uv run python -m integration.stack up     # build, start, wait until healthy (cleans up if not)
  uv run python -m integration.stack logs   # recent container logs
  uv run python -m integration.stack down   # remove the stack and its volume (unless KEEP=1)

Isolation from anything on the developer's machine:

- its own Compose project name (containers, network and volume never collide with the local
  `spendwise` stack), its own image tag and its own port;
- `docker compose` runs with a scrubbed environment and `--env-file` pointing at an empty file,
  so neither a repo-root `.env` nor shell variables such as POSTGRES_PASSWORD or COMPOSE_FILE can
  change the stack under test;
- a fresh random database password for every run (nothing secret is committed).

Settings (all optional), read from the environment of the test run:

  SPENDWISE_IT_PROJECT   Compose project name     (default: spendwise-it)
  SPENDWISE_IT_PORT      port on 127.0.0.1        (default: 18000)
  SPENDWISE_IT_IMAGE     tag for the built image  (default: spendwise:integration)
  SPENDWISE_IT_TIMEOUT   seconds to wait for the services to become healthy after they start
                         (default: 600; building the image is not counted)
  SPENDWISE_IT_KEEP=1    leave the stack and its volume running afterwards, for debugging
  SPENDWISE_IT_LOG_FILE  if set, the integration tests write the run's container logs there
"""

import contextlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# The same files `docker compose up` uses locally: the deployment definition plus the local
# override (published port, image tag, plain-HTTP cookie), all driven by the values below.
COMPOSE_FILES = (REPO_ROOT / "compose.yaml", REPO_ROOT / "compose.override.yaml")

# Only what the Docker CLI needs to find and talk to the daemon is passed through.
PASSTHROUGH_ENV = (
    "PATH",
    "HOME",
    "USER",
    "TMPDIR",
    "XDG_RUNTIME_DIR",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CONFIG",
    "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY",
)


# Hard limit for any single docker compose command, including a cold image build.
COMMAND_TIMEOUT = 3600


class StackError(RuntimeError):
    pass


def parse_docker_time(value: str) -> datetime:
    """Docker's RFC 3339 timestamps carry nanoseconds; keep microseconds."""
    match = re.fullmatch(r"(.+T\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d:\d\d)", value)
    if match is None:
        raise ValueError(f"unexpected Docker timestamp: {value!r}")
    seconds, fraction, zone = match.groups()
    zone = "+00:00" if zone == "Z" else zone
    return datetime.fromisoformat(f"{seconds}.{(fraction or '0')[:6].ljust(6, '0')}{zone}")


@dataclass
class Stack:
    project: str = "spendwise-it"
    port: int = 18000
    image: str = "spendwise:integration"
    timeout: int = 600
    keep: bool = False
    db_password: str = field(default_factory=lambda: secrets.token_hex(16))
    # Filled by record_startup() right after the first `up`.
    db_first_healthy: datetime | None = None
    # Logs of containers that were already removed (a restart replaces them), oldest first.
    previous_logs: list[str] = field(default_factory=list)
    app_started: datetime | None = None

    @classmethod
    def from_env(cls) -> "Stack":
        env = os.environ
        return cls(
            project=env.get("SPENDWISE_IT_PROJECT", "spendwise-it"),
            port=int(env.get("SPENDWISE_IT_PORT", "18000")),
            image=env.get("SPENDWISE_IT_IMAGE", "spendwise:integration"),
            timeout=int(env.get("SPENDWISE_IT_TIMEOUT", "600")),
            keep=env.get("SPENDWISE_IT_KEEP") == "1",
        )

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    # --- docker compose ----------------------------------------------------------------------

    def _env(self) -> dict[str, str]:
        env = {name: os.environ[name] for name in PASSTHROUGH_ENV if name in os.environ}
        env.update(
            POSTGRES_DB="spendwise",
            POSTGRES_USER="spendwise",
            POSTGRES_PASSWORD=self.db_password,
            APP_PORT=str(self.port),
            SPENDWISE_IMAGE=self.image,
            AI_PROVIDER="fake",
            SESSION_COOKIE_SECURE="false",
            SESSION_TTL_DAYS="14",
        )
        return env

    def compose(self, *args: str, timeout: int = COMMAND_TIMEOUT) -> subprocess.CompletedProcess:
        command = [
            "docker",
            "compose",
            *(arg for path in COMPOSE_FILES for arg in ("--file", str(path))),
            "--project-name",
            self.project,
            "--env-file",
            os.devnull,  # never read the repo-root .env
            *args,
        ]
        try:
            result = subprocess.run(
                command,
                cwd=REPO_ROOT,
                env=self._env(),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise StackError(f"`docker compose {' '.join(args)}` took over {timeout}s") from None
        except FileNotFoundError:
            raise StackError("Docker is not installed or not on PATH.") from None
        if result.returncode != 0:
            raise StackError(
                f"`docker compose {' '.join(args)}` failed ({result.returncode}):\n"
                f"{result.stdout}\n{result.stderr}"
            )
        return result

    def check_prerequisites(self) -> None:
        if shutil.which("docker") is None:
            raise StackError("Docker is not installed or not on PATH.")
        try:
            self.compose("version")
        except StackError as error:
            raise StackError(f"Docker Compose v2 is required.\n{error}") from None
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", self.port)) == 0:
                raise StackError(
                    f"Port {self.port} is already in use. Set SPENDWISE_IT_PORT to a free port."
                )

    def up(self, build: bool) -> None:
        """Start the stack and wait (up to `timeout` seconds) until every service is healthy."""
        args = ["up", "--detach", "--wait", "--wait-timeout", str(self.timeout)]
        self.compose(*args, *(["--build"] if build else []))

    def record_startup(self) -> None:
        """When PostgreSQL first passed its health check, and when the app container started.

        Read straight after `up`: Docker keeps only the last few health checks per container.
        """
        checks = self.inspect("db")["State"]["Health"]["Log"]
        passed = [parse_docker_time(c["Start"]) for c in checks if c["ExitCode"] == 0]
        self.db_first_healthy = min(passed) if passed else None
        self.app_started = parse_docker_time(self.inspect("app")["State"]["StartedAt"])

    def down(self, volumes: bool) -> None:
        if self.services():  # keep what these containers logged before they are removed
            self.previous_logs.append(self.logs(tail=1000, include_previous=False))
        self.compose("down", "--remove-orphans", *(["--volumes"] if volumes else []))

    def services(self) -> dict[str, dict]:
        """`docker compose ps` for this project, keyed by service name."""
        out = self.compose("ps", "--all", "--format", "json").stdout.strip()
        if not out:
            return {}
        rows = (
            json.loads(out)
            if out.startswith("[")
            else [json.loads(line) for line in out.splitlines()]
        )
        return {row["Service"]: row for row in rows}

    def inspect(self, service: str) -> dict:
        container = self.services()[service]["ID"]
        result = subprocess.run(
            ["docker", "inspect", container], capture_output=True, text=True, check=True
        )
        return json.loads(result.stdout)[0]

    def volumes(self) -> list[str]:
        result = subprocess.run(
            [
                "docker",
                "volume",
                "ls",
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={self.project}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.split()

    def logs(self, tail: int = 200, include_previous: bool = True) -> str:
        """Recent container logs; by default also those of containers removed by a restart."""
        try:
            current = self.compose("logs", "--no-color", "--tail", str(tail), timeout=60).stdout
        except StackError as error:
            current = f"(could not read logs: {error})"
        if not include_previous or not self.previous_logs:
            return current
        return "\n--- (containers restarted) ---\n".join([*self.previous_logs, current])


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Isolated SpendWise Compose stack for tests.")
    parser.add_argument("command", choices=["up", "down", "logs"])
    command = parser.parse_args(argv).command
    stack = Stack.from_env()

    if command == "logs":
        print(stack.logs(tail=500))
        return 0
    if command == "down":
        if stack.keep:
            print(f"SPENDWISE_IT_KEEP=1: stack '{stack.project}' left running at {stack.base_url}")
        else:
            stack.down(volumes=True)
        return 0

    try:
        stack.check_prerequisites()
        stack.down(volumes=True)  # leftovers from an interrupted earlier run
        stack.up(build=True)
    except StackError as error:
        print(f"The Compose stack did not start:\n{error}\n--- logs ---\n{stack.logs()}")
        if not stack.keep:
            with contextlib.suppress(StackError):
                stack.down(volumes=True)
        return 1
    print(f"Stack '{stack.project}' is healthy at {stack.base_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
