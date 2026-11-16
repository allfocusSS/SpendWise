"""The AI on-call responder's deployment (compose.oncall.yaml) and code, as data.

The oncall smoke test (oncall_smoke/, CI job "Observability AI On-call") runs them against a real
stack; these check the rules they must follow: local only, internal network, no credentials, no
secret in Git, nothing that can reach beyond three read-only GET endpoints.
"""

import ast
import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
OVERLAY = ROOT / "compose.oncall.yaml"
DASHBOARD = ROOT / "compose.dashboard.yaml"
PACKAGE = ROOT / "deploy" / "observability" / "oncall-responder" / "oncall_responder"
SECRET_REF = re.compile(r"\$\{ONCALL_HMAC_SECRET:\?[^}]+\}")


@pytest.fixture(scope="module")
def overlay() -> dict[str, Any]:
    return yaml.safe_load(OVERLAY.read_text())


@pytest.fixture(scope="module")
def dashboard() -> dict[str, Any]:
    return yaml.safe_load(DASHBOARD.read_text())


def test_the_overlay_adds_the_responder_and_changes_only_the_receivers_environment(overlay) -> None:
    assert set(overlay) == {"services"}  # no network, volume or secret of its own
    assert set(overlay["services"]) == {"alert-receiver", "oncall-responder"}
    assert set(overlay["services"]["alert-receiver"]) == {"environment"}


def test_the_receiver_hands_incidents_to_the_responder_by_its_internal_name(overlay) -> None:
    environment = overlay["services"]["alert-receiver"]["environment"]
    assert set(environment) == {"ONCALL_RESPONDER_URL", "ONCALL_HMAC_SECRET"}
    assert environment["ONCALL_RESPONDER_URL"] == "http://oncall-responder:8090/incidents"
    assert SECRET_REF.fullmatch(environment["ONCALL_HMAC_SECRET"])


def test_the_dashboard_and_alerts_stacks_do_not_change(dashboard) -> None:
    # make dashboard and make alerts run without this overlay, exactly as before.
    receiver = dashboard["services"]["alert-receiver"]
    assert "environment" not in receiver and "oncall-responder" not in dashboard["services"]
    assert "ONCALL" not in DASHBOARD.read_text()


def test_the_responder_is_internal_unprivileged_read_only_and_credential_free(overlay) -> None:
    responder = overlay["services"]["oncall-responder"]
    image = responder["image"]
    assert re.fullmatch(r"python:3\.13\.\d+-alpine3\.\d+@sha256:[0-9a-f]{64}", image)
    receiver_image = yaml.safe_load(DASHBOARD.read_text())["services"]["alert-receiver"]["image"]
    assert image == receiver_image  # the same pinned base as the receiver
    assert responder["command"] == ["python", "-B", "-u", "-m", "oncall_responder"]
    for forbidden in (
        "ports",
        "expose",
        "privileged",
        "network_mode",
        "cap_add",
        "pid",
        "devices",
        "env_file",
        "secrets",
        "extra_hosts",
        "dns",
    ):
        assert forbidden not in responder, forbidden
    assert responder["networks"] == ["alerting"]  # internal: no route out, nothing published
    assert responder["user"] == "65534:65534"
    assert responder["read_only"] is True
    assert responder["cap_drop"] == ["ALL"]
    assert responder["security_opt"] == ["no-new-privileges:true"]
    assert (responder["mem_limit"], responder["pids_limit"]) == ("128m", 32)
    assert responder["volumes"] == ["./deploy/observability/oncall-responder:/app:ro"]
    (tmpfs,) = responder["tmpfs"]
    assert tmpfs.startswith("/var/lib/oncall:size=4m,mode=0700,uid=65534,")
    assert responder["working_dir"] == "/app"


def test_the_responders_only_configuration_is_three_read_only_urls_and_one_secret(overlay) -> None:
    environment = overlay["services"]["oncall-responder"]["environment"]
    assert set(environment) == {
        "ONCALL_HMAC_SECRET",
        "ONCALL_MODEL",
        "PROMETHEUS_URL",
        "LOKI_URL",
        "TEMPO_URL",
        "ONCALL_GRAFANA_ORIGIN",
    }
    assert SECRET_REF.fullmatch(environment["ONCALL_HMAC_SECRET"])  # required, no default
    assert environment["ONCALL_MODEL"] == "fake"
    assert environment["PROMETHEUS_URL"] == "http://lgtm:9090"
    assert environment["LOKI_URL"] == "http://lgtm:3100"
    assert environment["TEMPO_URL"] == "http://lgtm:3200"
    assert environment["ONCALL_GRAFANA_ORIGIN"] == "http://127.0.0.1:${GRAFANA_PORT:-3000}"
    for name in environment:  # no cloud, repository, database or model credentials
        assert not re.search(r"(?i)aws|github|gh_|database|postgres|anthropic|openai|api_key", name)


def test_nothing_in_git_holds_the_secret() -> None:
    files = [OVERLAY, ROOT / "docs" / "observability.md", ROOT / "README.md", ROOT / "Makefile"]
    text_files = {".py", ".json", ".toml", ".yaml", ".md"}
    files += [
        p
        for p in PACKAGE.parents[0].rglob("*")
        if p.is_file() and p.suffix in text_files and "__pycache__" not in p.parts
    ]
    assigned = re.compile(r"ONCALL_HMAC_SECRET\s*[:=]\s*(\S+)")
    for path in files:
        for value in assigned.findall(path.read_text()):
            # A reference (${...}), a command ($(openssl ...)), a variable ("$secret") or an
            # environment lookup is fine; a literal value is not.
            assert value.startswith(("$", '"$', "os.environ", "env.get")) or value in {
                "{secret}",
                "SECRET",
                "secret",
            }, (path.name, value)
    for path in files:
        text = path.read_text()
        assert not re.search(r"sk-ant-[A-Za-z0-9_-]{8,}", text), path.name
        assert not re.search(r"(?i)hmac[_ -]?secret[\"']?\s*[:=]\s*[\"'][^\"'$]{8,}", text), (
            path.name
        )


def test_the_responder_is_standard_library_only() -> None:
    allowed = set(sys.stdlib_module_names) | {"oncall_responder"}
    for path in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                assert name.split(".")[0] in allowed, (path.name, name)


def calls_in(path: Path) -> set[str]:
    return {
        ast.unparse(node.func)
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
    }


def test_the_responder_can_execute_nothing_and_reach_nothing_else() -> None:
    forbidden_modules = {
        "subprocess",
        "socket",
        "ssl",
        "ftplib",
        "smtplib",
        "telnetlib",
        "pickle",
        "ctypes",
    }
    for path in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text())
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        # The server listens, so it may name `socket` (for the shutdown constant and the type of a
        # connection); nothing else may touch it, and no module may connect (checked below).
        allowed = {"socket"} if path.name == "server.py" else set()
        assert imported.isdisjoint(forbidden_modules - allowed), path.name
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert names.isdisjoint({"eval", "exec", "compile", "__import__", "breakpoint"}), path.name
        for call in calls_in(path):
            assert not call.startswith(("os.system", "os.popen", "os.exec", "os.spawn")), call
            assert call not in {"open", "Path.open"}, (path.name, call)


def test_outbound_requests_exist_in_one_place_and_are_all_gets() -> None:
    users = [
        p.name
        for p in PACKAGE.glob("*.py")
        if "http.client" in p.read_text() and "import http.client" in p.read_text()
    ]
    assert users == ["evidence.py"]  # the one module that makes outbound requests
    assert "urllib.request" not in "".join(p.read_text() for p in PACKAGE.glob("*.py"))
    requests = [c for c in calls_in(PACKAGE / "evidence.py") if c.endswith(".request")]
    assert requests == ["connection.request"]
    text = (PACKAGE / "evidence.py").read_text()
    assert text.count('connection.request("GET"') == 1
    assert not re.search(r"\.request\(\s*(?!\"GET\")", text.replace('connection.request("GET"', ""))


def test_the_only_file_the_responder_writes_is_the_report_store() -> None:
    writers = []
    for path in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text())
        if any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            # (not "replace": str.replace is everywhere; the store's Path.replace is covered by it
            # being the module that also calls write_text)
            and n.func.attr in {"write_text", "write_bytes", "unlink", "mkdir", "touch", "rename"}
            for n in ast.walk(tree)
        ):
            writers.append(path.name)
    assert writers == ["store.py"]


@pytest.mark.parametrize(
    "path",
    [
        "compose.yaml",
        "deploy/aws/compose.aws.yaml",
        "deploy/aws/spendwise-stack.yaml",
        "render.yaml",
        "Dockerfile",
        ".github/workflows/promote-production.yml",
    ],
)
def test_the_responder_is_never_part_of_a_deployment(path) -> None:
    text = (ROOT / path).read_text()
    for name in ("oncall-responder", "oncall_responder", "ONCALL_HMAC_SECRET", "alert-receiver"):
        assert name not in text, (path, name)


def test_the_make_target_and_the_docker_context_know_the_suite() -> None:
    makefile = (ROOT / "Makefile").read_text()
    assert "oncall:\n\tcd backend && uv run pytest oncall_smoke $(ARGS)" in makefile
    assert ".PHONY:" in makefile and re.search(r"\.PHONY:.*\boncall\b", makefile)
    assert "backend/oncall_smoke" in (ROOT / ".dockerignore").read_text().splitlines()


def test_the_docs_list_every_query_the_responder_can_run() -> None:
    from oncall_responder.evidence import QUERIES

    docs = (ROOT / "docs" / "observability.md").read_text()
    for queries in QUERIES.values():
        for query in queries:
            assert f"`{query.id}`" in docs, query.id
            assert query.text.replace("@ENV@", "<environment>").replace("|", "\\|") in docs, (
                query.id
            )


def test_the_server_listens_but_never_connects_out() -> None:
    server_calls = calls_in(PACKAGE / "server.py")
    assert not [call for call in server_calls if call.startswith(("socket.", "socketserver."))]
    assert not [call for call in server_calls if call.endswith((".connect", ".create_connection"))]


def test_the_servers_thread_budget_fits_the_containers_process_limit() -> None:
    import re

    from oncall_responder import server

    limit = int(
        re.search(r"pids_limit: (\d+)", (ROOT / "compose.oncall.yaml").read_text()).group(1)
    )
    # A thread per open connection, plus the main thread, the worker and the reaper.
    assert limit > server.MAX_CONNECTIONS + 3
    receiver_limit = int(
        re.search(r"pids_limit: (\d+)", (ROOT / "compose.dashboard.yaml").read_text()).group(1)
    )
    receiver = (ROOT / "deploy/observability/alert-receiver/alert_receiver.py").read_text()
    receiver_cap = int(re.search(r"^MAX_CONNECTIONS = (\d+)", receiver, re.M).group(1))
    assert receiver_cap + 3 < receiver_limit  # (the handoff thread is the "worker" here)


def test_the_docs_state_the_authentication_boundary_and_the_real_confidence_rule() -> None:
    docs = (ROOT / "docs" / "observability.md").read_text()
    assert "authenticates the alert receiver, not Grafana" in docs
    assert "capped at `low` when no metric was observed" not in docs  # the old, wrong claim
    assert "a query that found nothing is not evidence" in docs.lower()
    assert "no environment but its own settings" not in docs
    assert "request deadline" in docs and "look-alike" in docs
