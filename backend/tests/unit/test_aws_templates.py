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
