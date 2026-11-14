"""AWS deployment files (deploy/aws): free-tier and security guardrails.

These read the CloudFormation templates and the Compose additions as data; nothing talks to AWS.
cfn-lint checks the templates against the CloudFormation schema (deploy/aws/README.md).
"""

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

AWS_DIR = Path(__file__).resolve().parents[3] / "deploy" / "aws"

FREE_TIER_INSTANCE_TYPES = {"t2.micro", "t3.micro", "t3.small", "t4g.micro", "t4g.small"}
FREE_TIER_EBS_GIB = 30

# Paid or out-of-scope services that must never appear in the stack (Issue #10).
FORBIDDEN_PREFIXES = (
    "AWS::RDS::",
    "AWS::ElasticLoadBalancing::",
    "AWS::ElasticLoadBalancingV2::",
    "AWS::ECS::",
    "AWS::EKS::",
    "AWS::ElastiCache::",
    "AWS::AutoScaling::",
    "AWS::Route53::",
    "AWS::SecretsManager::",
    "AWS::KMS::",
    "AWS::CloudWatch::",
    "AWS::Logs::",
)
FORBIDDEN_TYPES = {"AWS::EC2::NatGateway", "AWS::EC2::VPCEndpoint", "AWS::EC2::TransitGateway"}


class CloudFormationLoader(yaml.SafeLoader):
    """Reads short-form intrinsics in their long form: !Ref x as {"Ref": x}, !Sub as Fn::Sub."""


def _intrinsic(loader: yaml.SafeLoader, name: str, node: yaml.Node) -> dict[str, Any]:
    if isinstance(node, yaml.ScalarNode):
        value: Any = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {name if name == "Ref" else f"Fn::{name}": value}


CloudFormationLoader.add_multi_constructor("!", _intrinsic)


def load(name: str) -> dict[str, Any]:
    return yaml.load((AWS_DIR / name).read_text(), Loader=CloudFormationLoader)


@pytest.fixture(scope="module")
def stack() -> dict[str, Any]:
    return load("spendwise-stack.yaml")


def resources(template: dict[str, Any], type_: str) -> dict[str, dict[str, Any]]:
    return {k: r for k, r in template["Resources"].items() if r["Type"] == type_}


def render_user_data(stack: dict[str, Any]) -> str:
    """The first-boot script with sample values in place of CloudFormation's substitutions."""
    script, _variables = stack["Resources"]["Instance"]["Properties"]["UserData"]["Fn::Base64"][
        "Fn::Sub"
    ]
    values = {
        "AWS::StackName": "spendwise",
        "AWS::Region": "eu-central-1",
        "ElasticIp": "203.0.113.10",
        "DataVolumeId": "vol-0123456789abcdef0",
        "GitHubRepository": "owner/SpendWise",
        "GitRef": "main",
        "DeployKeyParameterName": "/spendwise/github-deploy-key",
        "SiteAddress": "203.0.113.10",
        "AcmeProfile": "shortlived",
    }
    escaped = script.replace("${!", "\0")
    unknown = set(re.findall(r"\$\{([^}]+)\}", escaped)) - values.keys()
    assert not unknown, f"unresolved substitutions: {unknown}"
    rendered = re.sub(r"\$\{([^}]+)\}", lambda m: values[m.group(1)], escaped)
    return rendered.replace("\0", "${")


def test_no_paid_or_out_of_scope_services(stack) -> None:
    for name, resource in stack["Resources"].items():
        assert not resource["Type"].startswith(FORBIDDEN_PREFIXES), name
        assert resource["Type"] not in FORBIDDEN_TYPES, name


def test_exactly_one_free_tier_instance(stack) -> None:
    assert len(resources(stack, "AWS::EC2::Instance")) == 1
    instance_type = stack["Parameters"]["InstanceType"]
    assert set(instance_type["AllowedValues"]) <= FREE_TIER_INSTANCE_TYPES
    assert instance_type["Default"] == "t3.micro"


def test_cpu_bursts_are_never_billed_by_default(stack) -> None:
    assert stack["Parameters"]["CpuCreditMode"]["Default"] == "standard"
    credits = stack["Resources"]["Instance"]["Properties"]["CreditSpecification"]["CPUCredits"]
    assert credits == {"Ref": "CpuCreditMode"}


def test_ami_is_pinned_so_updates_do_not_replace_the_instance(stack) -> None:
    image = stack["Parameters"]["ImageId"]
    assert image["Type"] == "AWS::EC2::Image::Id"
    assert "Default" not in image


def test_storage_fits_the_free_tier_and_is_encrypted(stack) -> None:
    params = stack["Parameters"]
    assert params["RootVolumeSize"]["MaxValue"] + params["DataVolumeSize"]["MaxValue"] <= (
        FREE_TIER_EBS_GIB
    )
    (root,) = stack["Resources"]["Instance"]["Properties"]["BlockDeviceMappings"]
    assert root["Ebs"]["Encrypted"] is True
    assert root["Ebs"]["VolumeType"] == "gp3"
    data = stack["Resources"]["DataVolume"]
    assert data["Properties"]["Encrypted"] is True
    assert data["Properties"]["VolumeType"] == "gp3"
    assert "Iops" not in data["Properties"] and "Throughput" not in data["Properties"]


def test_the_database_volume_survives_stack_deletion_and_replacement(stack) -> None:
    data = stack["Resources"]["DataVolume"]
    assert data["DeletionPolicy"] == "Retain"
    assert data["UpdateReplacePolicy"] == "Retain"


def test_only_http_and_https_are_open(stack) -> None:
    (group,) = resources(stack, "AWS::EC2::SecurityGroup").values()
    ingress = group["Properties"]["SecurityGroupIngress"]
    assert {(rule["FromPort"], rule["ToPort"]) for rule in ingress} == {(80, 80), (443, 443)}
    assert all(rule["IpProtocol"] == "tcp" for rule in ingress)
    assert not resources(stack, "AWS::EC2::SecurityGroupIngress")


def test_instance_metadata_requires_imdsv2_and_is_out_of_reach_of_containers(stack) -> None:
    metadata = stack["Resources"]["LaunchTemplate"]["Properties"]["LaunchTemplateData"][
        "MetadataOptions"
    ]
    assert metadata["HttpTokens"] == "required"
    assert metadata["HttpPutResponseHopLimit"] == 1


def test_instance_role_reads_only_the_deploy_key(stack) -> None:
    role = stack["Resources"]["InstanceRole"]["Properties"]
    (policy,) = role["Policies"]["Fn::If"][1]
    (statement,) = policy["PolicyDocument"]["Statement"]
    assert statement["Action"] == "ssm:GetParameter"
    assert statement["Resource"]["Fn::Sub"].endswith(":parameter${DeployKeyParameterName}")
    assert [arn["Fn::Sub"].rsplit("/", 1)[1] for arn in role["ManagedPolicyArns"]] == [
        "AmazonSSMManagedInstanceCore"
    ]


def test_first_boot_script_is_valid_bash(stack, tmp_path: Path) -> None:
    script = tmp_path / "user-data.sh"
    script.write_text(render_user_data(stack))
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_first_boot_script_fits_in_user_data(stack) -> None:
    assert len(render_user_data(stack).encode()) < 16 * 1024


def test_first_boot_script_holds_no_secret_and_never_prints_the_password(stack) -> None:
    script = render_user_data(stack)
    assert "password=$(openssl rand -hex 32)" in script  # a failure stops the script
    assert "has no usable POSTGRES_PASSWORD" in script
    assert not re.search(r"POSTGRES_PASSWORD=[A-Za-z0-9]", script)
    assert "BEGIN OPENSSH PRIVATE KEY" not in script


def test_docker_plugins_are_pinned_and_checksum_verified(stack) -> None:
    script = render_user_data(stack)
    shas = re.findall(r"(?:compose|buildx)_sha=(\S+)", script)
    assert len(shas) == 4
    assert all(re.fullmatch(r"[0-9a-f]{64}", sha) for sha in shas)
    assert "sha256sum -c -" in script


def test_budget_alerts_by_email_before_and_at_the_limit() -> None:
    budget = load("budget.yaml")
    (resource,) = resources(budget, "AWS::Budgets::Budget").values()
    props = resource["Properties"]
    assert props["Budget"]["BudgetType"] == "COST"
    assert props["Budget"]["TimeUnit"] == "MONTHLY"
    assert props["Budget"]["CostTypes"]["IncludeCredit"] is False
    notifications = props["NotificationsWithSubscribers"]
    assert {
        (n["Notification"]["NotificationType"], n["Notification"]["Threshold"])
        for n in notifications
    } == {("ACTUAL", 80), ("ACTUAL", 100), ("FORECASTED", 100)}
    assert all(s["SubscriptionType"] == "EMAIL" for n in notifications for s in n["Subscribers"])


def test_compose_additions_publish_only_caddy() -> None:
    compose = yaml.safe_load((AWS_DIR / "compose.aws.yaml").read_text())
    services = compose["services"]
    assert "ports" not in services["app"]
    assert "db" not in services
    assert services["caddy"]["ports"] == ["80:80", "443:443"]


def test_database_lives_on_the_data_volume() -> None:
    compose = yaml.safe_load((AWS_DIR / "compose.aws.yaml").read_text())
    options = compose["volumes"]["pgdata"]["driver_opts"]
    assert options["o"] == "bind"
    assert options["device"].startswith("${SPENDWISE_DATA_DIR:?")


# --- Continuous deployment from GitHub Actions (Issue #11) ---
#
# Mode B, the default (GitHubDeployMode=self-hosted-runner): AWS Free Tier Projects have a Service
# Control Policy (DenyIAMRestrictedActions) that denies iam:*Provider*, so the stack must create
# no OIDC provider; a runner on the instance deploys. Mode A (oidc-ssm) adds the OIDC resources.
OIDC_RESOURCES = {"GitHubOidcProvider", "DeployDocument", "GitHubDeployRole"}
OIDC_OUTPUTS = {"GitHubDeployRoleArn", "DeployDocumentName", "GitHubOidcProviderArn"}

# gh api repos/allfocusSS/SpendWise --jq '{repo_id: .id, owner_id: .owner.id}'. The repository
# uses GitHub's immutable OIDC subject format (created after 15 July 2026), which embeds both IDs.
EXPECTED_DEPLOY_SUBJECT = "repo:allfocusSS@189591398/SpendWise@1441102769:ref:refs/heads/main"


def evaluate(stack: dict[str, Any], value: Any, names: dict[str, Any] | None = None) -> Any:
    """Resolves the intrinsics the trust policy uses, with the parameters' defaults."""
    names = names or {}
    if isinstance(value, dict) and len(value) == 1:
        ((key, arg),) = value.items()
        if key == "Ref":
            return names[arg] if arg in names else stack["Parameters"][arg]["Default"]
        if key == "Fn::Select":
            return evaluate(stack, arg[1], names)[arg[0]]
        if key == "Fn::Split":
            return evaluate(stack, arg[1], names).split(arg[0])
        if key == "Fn::Sub":
            template, variables = arg if isinstance(arg, list) else (arg, {})
            values = {k: evaluate(stack, v, names) for k, v in variables.items()}
            return re.sub(
                r"\$\{([^}]+)\}",
                lambda m: values.get(m.group(1)) or evaluate(stack, {"Ref": m.group(1)}, names),
                template,
            )
    return value


def condition_holds(stack: dict[str, Any], name: str, overrides: dict[str, str]) -> bool:
    """Evaluates a stack condition with parameter defaults, plus overrides."""

    def value(node: Any) -> Any:
        if isinstance(node, dict) and set(node) == {"Ref"}:
            ref = node["Ref"]
            return overrides.get(ref, stack["Parameters"][ref].get("Default"))
        return node

    def holds(node: Any) -> bool:
        ((key, arg),) = node.items()
        if key == "Fn::Equals":
            return value(arg[0]) == value(arg[1])
        if key == "Fn::And":
            return all(holds(item) for item in arg)
        if key == "Fn::Not":
            return not holds(arg[0])
        if key in ("Condition", "Fn::Condition"):  # !Condition reads as Fn::Condition
            return condition_holds(stack, arg, overrides)
        raise AssertionError(f"unsupported condition {key}")

    return holds(stack["Conditions"][name])


def created(stack: dict[str, Any], section: str, overrides: dict[str, str]) -> set[str]:
    return {
        name
        for name, body in stack[section].items()
        if "Condition" not in body or condition_holds(stack, body["Condition"], overrides)
    }


def deploy_role(stack: dict[str, Any]) -> dict[str, Any]:
    return stack["Resources"]["GitHubDeployRole"]["Properties"]


def deploy_statements(stack: dict[str, Any]) -> list[dict[str, Any]]:
    (policy,) = deploy_role(stack)["Policies"]
    return policy["PolicyDocument"]["Statement"]


def test_free_tier_mode_is_the_default_and_creates_no_oidc_resources(stack) -> None:
    mode = stack["Parameters"]["GitHubDeployMode"]
    assert mode["Default"] == "self-hosted-runner"
    assert set(mode["AllowedValues"]) == {"self-hosted-runner", "oidc-ssm"}
    resources_ = created(stack, "Resources", {})
    assert not OIDC_RESOURCES & resources_
    assert not OIDC_OUTPUTS & created(stack, "Outputs", {})
    # Nothing else in the default template is an identity provider either.
    assert not [r for r in resources_ if "Provider" in stack["Resources"][r]["Type"]]
    # Updating the existing stack with defaults keeps every resource it already had.
    assert set(stack["Resources"]) - OIDC_RESOURCES <= resources_


def test_oidc_mode_creates_the_oidc_resources(stack) -> None:
    mode = {"GitHubDeployMode": "oidc-ssm"}
    assert created(stack, "Resources", mode) >= OIDC_RESOURCES
    assert created(stack, "Outputs", mode) >= OIDC_OUTPUTS
    # With an existing provider passed in, the stack does not create (or own) one.
    existing = mode | {
        "ExistingGitHubOidcProviderArn": "arn:aws:iam::123456789012:oidc-provider/"
        "token.actions.githubusercontent.com"
    }
    assert "GitHubOidcProvider" not in created(stack, "Resources", existing)
    assert {"DeployDocument", "GitHubDeployRole"} <= created(stack, "Resources", existing)


def test_github_oidc_provider_issues_tokens_for_sts_only(stack) -> None:
    provider = stack["Resources"]["GitHubOidcProvider"]
    assert provider["Type"] == "AWS::IAM::OIDCProvider"
    assert provider["Properties"]["Url"] == "https://token.actions.githubusercontent.com"
    assert provider["Properties"]["ClientIdList"] == ["sts.amazonaws.com"]
    # An account holds one provider per URL, so an existing one can be passed in instead.
    assert provider["Condition"] == "CreateGitHubOidcProvider"
    assert stack["Parameters"]["ExistingGitHubOidcProviderArn"]["Default"] == ""


def test_deploy_role_trusts_only_spendwise_main_through_oidc(stack) -> None:
    (statement,) = deploy_role(stack)["AssumeRolePolicyDocument"]["Statement"]
    assert statement["Effect"] == "Allow"
    assert statement["Action"] == "sts:AssumeRoleWithWebIdentity"
    assert set(statement["Principal"]) == {"Federated"}
    federated = statement["Principal"]["Federated"]["Fn::If"]
    assert federated == [
        "CreateGitHubOidcProvider",
        {"Ref": "GitHubOidcProvider"},
        {"Ref": "ExistingGitHubOidcProviderArn"},
    ]
    # Exact matches only: no StringLike, so no wildcard can widen the trust.
    assert set(statement["Condition"]) == {"StringEquals"}
    conditions = statement["Condition"]["StringEquals"]
    assert set(conditions) == {
        "token.actions.githubusercontent.com:aud",
        "token.actions.githubusercontent.com:sub",
    }
    assert conditions["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    subject = evaluate(stack, conditions["token.actions.githubusercontent.com:sub"])
    assert subject == EXPECTED_DEPLOY_SUBJECT


@pytest.mark.parametrize(
    "parameter",
    ["GitHubOwnerId", "GitHubRepositoryId", "GitHubDeployBranch", "GitHubRepository"],
)
def test_deploy_subject_changes_with_every_part_of_the_identity(stack, parameter) -> None:
    (statement,) = deploy_role(stack)["AssumeRolePolicyDocument"]["Statement"]
    sub = statement["Condition"]["StringEquals"]["token.actions.githubusercontent.com:sub"]
    other = "someone/else" if parameter == "GitHubRepository" else "999"
    assert evaluate(stack, sub, {parameter: other}) != EXPECTED_DEPLOY_SUBJECT


def test_deploy_role_can_only_run_the_deploy_document_on_the_instance(stack) -> None:
    role = deploy_role(stack)
    assert "ManagedPolicyArns" not in role
    statements = deploy_statements(stack)
    assert all(s["Effect"] == "Allow" for s in statements)
    assert {s["Action"] for s in statements} == {"ssm:SendCommand", "ssm:GetCommandInvocation"}

    (send,) = [s for s in statements if s["Action"] == "ssm:SendCommand"]
    assert [r["Fn::Sub"] for r in send["Resource"]] == [
        "arn:${AWS::Partition}:ec2:${AWS::Region}:${AWS::AccountId}:instance/${Instance}",
        "arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}:document/${DeployDocument}",
    ]
    # GetCommandInvocation has no resource-level permissions; it only reads results.
    (read,) = [s for s in statements if s["Action"] == "ssm:GetCommandInvocation"]
    assert read["Resource"] == "*"


def test_no_role_gets_administrator_or_wildcard_permissions(stack) -> None:
    text = (AWS_DIR / "spendwise-stack.yaml").read_text()
    assert "AdministratorAccess" not in text
    assert "PowerUserAccess" not in text
    assert "document/AWS-" not in text  # no AWS-owned document such as AWS-RunShellScript
    assert "iam:PassRole" not in text
    for statement in deploy_statements(stack):
        assert "*" not in statement["Action"]
        assert not statement["Action"].startswith(("ec2:", "iam:", "ssm:StartSession"))


def test_deploy_document_runs_only_spendwise_deploy_with_a_commit_sha(stack) -> None:
    document = stack["Resources"]["DeployDocument"]["Properties"]
    assert document["DocumentType"] == "Command"
    assert document["TargetType"] == "/AWS::EC2::Instance"
    content = document["Content"]
    parameters = content["parameters"]
    assert set(parameters) == {"CommitSha"}
    assert parameters["CommitSha"]["allowedPattern"] == "^[0-9a-f]{40}$"
    (step,) = content["mainSteps"]
    assert step["action"] == "aws:runShellScript"
    assert step["inputs"]["runCommand"] == ["/usr/local/bin/spendwise-deploy '{{ CommitSha }}'"]
    assert "spendwise-deploy" in render_user_data(stack)


def test_continuous_deployment_adds_nothing_that_costs_money(stack) -> None:
    added = {"GitHubOidcProvider", "DeployDocument", "GitHubDeployRole"}
    assert {stack["Resources"][name]["Type"] for name in added} == {
        "AWS::IAM::OIDCProvider",
        "AWS::SSM::Document",
        "AWS::IAM::Role",
    }


def test_outputs_give_the_github_repository_variables(stack) -> None:
    outputs = stack["Outputs"]
    assert outputs["GitHubDeployRoleArn"]["Value"] == {"Fn::GetAtt": "GitHubDeployRole.Arn"}
    assert outputs["DeployDocumentName"]["Value"] == {"Ref": "DeployDocument"}
    assert outputs["InstanceId"]["Value"] == {"Ref": "Instance"}
    for name, variable in [
        ("GitHubDeployRoleArn", "AWS_DEPLOY_ROLE_ARN"),
        ("DeployDocumentName", "AWS_DEPLOY_DOCUMENT"),
        ("InstanceId", "AWS_INSTANCE_ID"),
    ]:
        assert variable in outputs[name]["Description"]
    assert "GitHubOidcProviderArn" in outputs
