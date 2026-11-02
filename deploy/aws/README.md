# SpendWise on AWS (EC2 + CloudFormation)

A small, free-tier-sized AWS deployment for SpendWise: **one EC2 instance running the same Docker
Compose stack as local development**, described in CloudFormation so it can be created and
deleted reproducibly.

```
GitHub (this repository, read with a deploy key)
        │  git fetch, docker compose build
        ▼
EC2 instance (Amazon Linux 2023, t3.micro) ── Elastic IP ── HTTPS :443 / HTTP :80 (redirect)
        │
Docker Compose (compose.yaml + deploy/aws/compose.aws.yaml)
   ├── caddy    ports 80/443, automatic Let's Encrypt certificate, proxies to app:8000
   ├── app      SpendWise image (UI + API), not published
   └── db       PostgreSQL 18, not published
        │
EBS data volume (encrypted, retained) at /srv/spendwise
   ├── postgres/   the database
   ├── caddy/      certificates
   └── secrets/    the generated database password
```

| File | What it is |
|---|---|
| `budget.yaml` | A monthly AWS Budget with email alerts. Deploy it **first**. |
| `spendwise-stack.yaml` | The network, security group, IAM role, data volume, Elastic IP and instance. |
| `compose.aws.yaml` | EC2 additions to `compose.yaml`: Caddy and the database on the data volume. |
| `Caddyfile` | HTTPS and the reverse proxy. |

Nothing in these files is secret. The database password is generated on the instance at first
boot. The GitHub deploy key is stored in SSM Parameter Store, which you do yourself.

**Not used, on purpose:** RDS, Aurora, load balancers, NAT gateways, ElastiCache, ECS/Fargate,
EKS, autoscaling, Route 53, Secrets Manager, CloudWatch alarms or paid monitoring. Issue #10
first proposed ECS Fargate and RDS; both cost money every month outside short trials, so the
course's single-instance flow replaces them. PostgreSQL runs in Compose on the instance and is
never exposed to the network.

## What the stack creates

| Resource | Details | Cost |
|---|---|---|
| VPC, public subnet, internet gateway, route table | `10.20.0.0/16`, one subnet in one zone | free |
| Security group | inbound TCP 80 and 443 only; outbound TCP 80 and 443 only | free |
| IAM role and instance profile | Session Manager access (`AmazonSSMManagedInstanceCore`) and `ssm:GetParameter` on the one deploy key parameter | free |
| Launch template | IMDSv2 required, hop limit 1, so containers cannot read the instance's credentials | free |
| EC2 instance | `t3.micro` by default, CPU credits `standard` (never billed for bursts) | free tier / credits |
| Root volume | 20 GiB gp3, encrypted, deleted with the instance | free tier / credits |
| Data volume | 8 GiB gp3, encrypted, **retained** when the stack is deleted | free tier / credits |
| Elastic IP | stable public IPv4, released when the stack is deleted | see below |
| Wait condition `AppReady` | stack creation finishes only when the first deploy is healthy | free |

There's no SSH and no key pair: you get a shell through **SSM Session Manager**, which needs no
open port.

## Costs and the free tier

Check which AWS free tier applies to your account before deploying:

- **Free plan (accounts created on or after 15 July 2025):** usage is paid from free credits
  ($100 at signup, up to $100 more for completing activities) for up to 6 months. Eligible
  instance types are `t3.micro`, `t3.small`, `t4g.micro` and `t4g.small`. As a rough guide, this
  stack uses about **$15 of credits a month** at list prices: a `t3.micro` is about $9 a month,
  28 GiB of gp3 about $3, and a public IPv4 address about $3.65. A `t4g.micro` (arm64) is a little
  cheaper. On the free plan AWS does not charge beyond your credits.
- **Legacy free tier (older accounts, first 12 months):** 750 hours a month of `t2.micro` (or
  `t3.micro` in regions without `t2.micro`), 30 GiB of EBS, and 750 hours of public IPv4. One
  instance with 28 GiB of disk fits, so the stack costs **$0**. In the EC2 console's launch
  wizard, check which of `t2.micro` and `t3.micro` is marked "Free tier eligible" in your
  region, and pass that as `InstanceType`.

Prices are approximate. Check them with the [AWS Pricing Calculator](https://calculator.aws/)
for your region.

What can still cost money, and how this setup avoids it:

- **CPU bursts.** `CpuCreditMode=standard` (the default) throttles the instance to its baseline
  instead of billing for extra CPU. `unlimited` is faster but can be billed if average CPU stays
  above baseline.
- **Storage beyond 30 GiB.** The parameters cap the root volume at 20 GiB and the data volume at
  10 GiB. There are no snapshots and no provisioned IOPS or throughput.
- **The Elastic IP.** Every public IPv4 address is billed per hour unless the free tier covers it,
  including while the instance is stopped. Deleting the stack releases it.
- **A retained data volume.** It survives stack deletion so the database isn't lost by accident,
  and it keeps costing about $0.10 per GiB a month until you delete it (see Tearing down).
- **Data transfer out.** The first 100 GB a month to the internet are free.

Session Manager, Parameter Store standard parameters, the default `aws/ebs` and `aws/ssm`
encryption keys, IAM, the VPC itself and budgets with email alerts are all free.

## Security

- **Database:** PostgreSQL has no published port. It is reachable only on the Compose network,
  by the app. There is no RDS endpoint and no security group rule for 5432.
- **App:** port 8000 is not published either. Only Caddy reaches it, so the app's trust of
  `X-Forwarded-Proto` (to set Secure cookies) only ever sees Caddy's header.
- **HTTPS:** Caddy gets a Let's Encrypt certificate automatically and redirects HTTP to HTTPS.
  Session cookies are `Secure`, `HttpOnly` and `SameSite=Lax`.
- **Secrets:**
  - The database password is 64 random hex characters generated at first boot. It's stored in
    `/srv/spendwise/secrets/spendwise.env` (root only, mode 600) on the encrypted data volume,
    next to the database it belongs to, and is never printed.
  - The GitHub deploy key is a read-only key stored as an SSM SecureString parameter. It's
    fetched for each deploy and deleted from disk afterwards.
  - Secrets Manager isn't used because it costs $0.40 per secret a month.
- **Disks:** both EBS volumes are encrypted with the default AWS-managed key.
- **Instance metadata:** IMDSv2 only, with a hop limit of 1, so containers can't read the
  instance's credentials.
- **Outbound traffic:** TCP 80 and 443 only. Git over SSH uses `ssh.github.com:443`, with
  GitHub's published host keys pinned.

Not covered yet: rate limiting on `/api/auth/login` and `/api/auth/signup`. The stock Caddy
image has no rate limiter, so login attempts are not limited (README, "Before deploying").

## HTTPS: domain name or IP address

- **With `DomainName`:** create a DNS `A` record for the name pointing at the stack's
  `PublicIp` output. Caddy gets a normal certificate once DNS resolves.
- **Without a domain (the default):** Caddy serves `https://<Elastic IP>` with a Let's Encrypt
  IP address certificate. These are valid for about 6 days (the `shortlived` profile, generally
  available since January 2026) and Caddy renews them automatically. If issuance fails, use a
  domain name instead.

You can't test either from a local machine: Let's Encrypt has to reach the instance on port 80
or 443.

## Before you start

- An AWS account, and the [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
  signed in to it (`aws sts get-caller-identity`). For shell access, also install the
  [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html).
- A region. The commands use `eu-central-1` (Frankfurt), the same region as the Render setup.
- The branch that adds `deploy/aws/` merged into `main`, because the instance deploys
  `GitRef=main` from GitHub.

```bash
export AWS_REGION=eu-central-1
```

## Steps

### 1. Budget alerts first

```bash
aws cloudformation deploy --stack-name spendwise-budget \
  --template-file deploy/aws/budget.yaml \
  --parameter-overrides AlertEmail=you@example.com MonthlyLimitUsd=5
```

This emails you when actual spending passes 80% and 100% of the limit, and when the month's
forecast passes 100%. It measures usage **before credits**, so on the free plan you also hear
about usage that is eating into your credits; raise `MonthlyLimitUsd` to about 20 if those emails
are too noisy. In the Billing console, under Billing preferences, also turn on **Free Tier usage
alerts**. A budget only alerts; it never stops resources.

### 2. A read-only deploy key (the repository is private)

```bash
ssh-keygen -t ed25519 -N '' -C spendwise-ec2 -f spendwise-deploy-key
```

1. In GitHub, open the repository's Settings, then Deploy keys, then Add deploy key. Paste
   `spendwise-deploy-key.pub` and leave "Allow write access" **off**.
2. Store the private key as a SecureString and delete the local copies:

   ```bash
   aws ssm put-parameter --name /spendwise/github-deploy-key --type SecureString \
     --value file://spendwise-deploy-key
   rm spendwise-deploy-key spendwise-deploy-key.pub
   ```

For a public repository, skip this step and pass `DeployKeyParameterName=""` instead.

### 3. Look up the Amazon Linux 2023 AMI

```bash
AMI=$(aws ssm get-parameter --query Parameter.Value --output text \
  --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64)
# t4g instances (arm64): .../al2023-ami-kernel-default-arm64
echo "$AMI"
```

The AMI is a plain parameter on purpose. A new AMI replaces the instance, so that only happens
when you pass a new ID.

### 4. Create the stack

```bash
aws cloudformation deploy --stack-name spendwise \
  --template-file deploy/aws/spendwise-stack.yaml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides ImageId="$AMI"
  # optional: InstanceType=t2.micro  DomainName=spendwise.example.com
```

The command returns when the first deploy is healthy. In standard CPU mode a `t3.micro` starts
with no CPU credits, so building the image can take 20 to 45 minutes. A `t2.micro` (30 launch
credits) or `CpuCreditMode=unlimited` is faster. If setup fails, CloudFormation rolls the stack
back. A newly created data volume is kept (see Tearing down); add `--disable-rollback` to keep
the instance for debugging instead.

### 5. Open it

```bash
aws cloudformation describe-stacks --stack-name spendwise \
  --query 'Stacks[0].Outputs' --output table
```

Open `SiteUrl`. The certificate is usually ready within a minute or two.

### 6. Verify

Run the checklist in the main README ([Verify the deployment](../../README.md#verify-the-deployment))
with:

```bash
APP=https://<SiteUrl host>              # SiteUrl from the outputs
PW='<a password of 12+ characters>'     # only for these throwaway check accounts
```

For the persistence step, restart everything (`sudo spendwise-deploy` on the instance, or reboot
it), then rerun that line. Also check that nothing but 80 and 443 answers:

```bash
IP=<PublicIp>
curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' "http://$IP/"   # 308 https://…
nc -zv -w 5 "$IP" 5432; nc -zv -w 5 "$IP" 8000; nc -zv -w 5 "$IP" 22      # all time out
```

## Operating it

Open a shell with the `SessionCommand` output (`aws ssm start-session --target i-…`), then:

```bash
sudo tail -n 50 /var/log/spendwise-bootstrap.log          # first-boot log
sudo spendwise-deploy                                      # deploy the latest main
sudo spendwise-deploy <branch|tag|commit>                  # deploy something else

cd /opt/spendwise/src
c="sudo docker compose -f compose.yaml -f deploy/aws/compose.aws.yaml --env-file /srv/spendwise/secrets/spendwise.env --env-file /etc/spendwise/deploy.env"
$c ps                     # db and app healthy, caddy up
$c logs --tail 100 app    # application log (caddy: certificates)
```

- **Deploys** happen on the instance (`spendwise-deploy`), not through stack updates: the
  first-boot script runs only once. Automated deploys from GitHub Actions (OIDC) are a separate,
  later issue.
- **Backups.** The free tier has no automatic backups. Take a dump and copy it off the instance:

  ```bash
  $c exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > ~/spendwise-$(date +%F).sql.gz
  ```

  EBS snapshots also work, but storage beyond the free tier is billed.
- **OS updates:** `sudo dnf upgrade --releasever=latest -y`, then reboot. Docker and the stack
  start again by themselves, after the data volume is mounted.
- **Stopping the instance** stops instance-hour charges. The volumes and the Elastic IP are
  still billed (or still count against the free tier).

## Tearing down

```bash
aws cloudformation delete-stack --stack-name spendwise
aws cloudformation wait stack-delete-complete --stack-name spendwise
```

This deletes everything except the **data volume**, which is kept on purpose. To reuse it,
create the stack again with `ExistingDataVolumeId=vol-…` (the `DataVolumeId` output) in the
same availability zone; the database and password come back. To get rid of it, and its cost,
for good:

```bash
aws ec2 describe-volumes --filters Name=tag:spendwise:data,Values=true \
  --query 'Volumes[].[VolumeId,State,Size,CreateTime]' --output table
aws ec2 delete-volume --volume-id vol-…        # deletes the database permanently
```

Run the `describe-volumes` command after a failed first create too: each attempt leaves a
volume. Delete the deploy key parameter and the budget stack when you no longer need them.

## Checking the templates locally

Nothing here needs AWS credentials:

```bash
# CloudFormation schema and best practices
uvx cfn-lint deploy/aws/spendwise-stack.yaml deploy/aws/budget.yaml
# Free-tier and security guardrails
cd backend && uv run pytest tests/unit/test_aws_templates.py
```

The tests (part of the normal backend suite and CI) check, among other things:

- that no RDS, load balancer, NAT, ECS, EKS or other paid service is added;
- free-tier instance types and storage sizes;
- encrypted volumes and the retained data volume;
- that only ports 80 and 443 are open, and IMDSv2;
- the scope of the IAM permissions;
- that the first-boot script is valid bash with pinned, checksum-verified downloads;
- the budget's alerts;
- that Compose publishes only Caddy.
