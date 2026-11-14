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
| `spendwise-stack.yaml` | The network, security group, IAM roles, data volume, Elastic IP and instance, and the GitHub Actions deploy role. |
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
| GitHub OIDC provider (Mode A only) | `token.actions.githubusercontent.com`, audience `sts.amazonaws.com`, or an existing one. **Not created by default**: AWS Free Tier Projects deny `iam:*Provider*` (see [Automatic deploys](#automatic-deploys-from-github-actions)) | free |
| SSM document `<stack>-deploy` (Mode A only) | runs `spendwise-deploy <commit SHA>` and nothing else | free |
| IAM role `GitHubDeployRole` (Mode A only) | assumable only by GitHub Actions on `main` of this repository; may only run that document on this instance | free |

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

Session Manager, Run Command, Parameter Store standard parameters, the default `aws/ebs` and
`aws/ssm` encryption keys, IAM (including the OIDC provider), the VPC itself and budgets with
email alerts are all free.

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
- **Deploys from GitHub Actions:** no AWS access keys exist (see [Automatic deploys](#automatic-deploys-from-github-actions)).
  - In this account (Mode B), a runner on the instance deploys. It runs as an unprivileged user
    that may only run a root-owned wrapper through sudo, for the current head of `main`. Its job
    hook refuses every job but the `main` deploy, and it can't reach the instance metadata
    service.
  - In Mode A, each run gets one-hour OIDC credentials for a role that can only run
    `spendwise-deploy <commit SHA>` on this instance.

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
  first-boot script runs only once. Every push to `main` that passes CI is deployed
  automatically (next section); `spendwise-deploy` by hand is for anything else.
- **Backups.** The free tier has no automatic backups. Take a dump and copy it off the instance:

  ```bash
  $c exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > ~/spendwise-$(date +%F).sql.gz
  ```

  EBS snapshots also work, but storage beyond the free tier is billed.
- **OS updates:** `sudo dnf upgrade --releasever=latest -y`, then reboot. Docker and the stack
  start again by themselves, after the data volume is mounted.
- **Stopping the instance** stops instance-hour charges. The volumes and the Elastic IP are
  still billed (or still count against the free tier).

## Automatic deploys from GitHub Actions

Every push to `main` that passes the whole CI suite is deployed to the instance as that exact
commit (`github.sha`, never `main`). No AWS access key exists anywhere. There are two ways to do
it. The repository variable `AWS_DEPLOY_MODE` chooses the workflow job, and the stack parameter
`GitHubDeployMode` chooses the AWS resources:

| | Mode B: self-hosted deploy runner | Mode A: GitHub OIDC and SSM |
|---|---|---|
| For | **AWS Free Tier Projects (this account)** | standard AWS accounts |
| `GitHubDeployMode` (stack) | `self-hosted-runner` (the default) | `oidc-ssm` |
| `AWS_DEPLOY_MODE` (GitHub) | `self-hosted-runner` | `oidc-ssm` |
| Workflow job | `deploy-aws`, on the instance's own runner | `deploy-aws-oidc`, on a GitHub-hosted runner |
| AWS credentials used | none | one-hour role credentials from GitHub's OIDC token |
| AWS resources for deploys | none | OIDC provider, deploy role, SSM document |

With `AWS_DEPLOY_MODE` unset, neither job runs and nothing is deployed. Pull requests never
deploy in either mode, and every CI job (backend, frontend, integration, end-to-end) always runs
on GitHub-hosted runners.

> **Which mode to use.**
>
> - **GitHub recommends against self-hosted runners for public repositories.** This repository
>   is public.
> - Mode B is a **constrained fallback**, used only because this account's AWS Free Tier Project
>   Service Control Policy blocks IAM OIDC providers (`iam:*Provider*`). Its constraints are
>   listed below.
> - **The standard production recommendation remains Mode A:** GitHub OIDC with SSM, in an AWS
>   account that permits federation. It runs nothing on the production host on GitHub's behalf
>   and needs no runner. Move to it as soon as the deployment runs in such an account.

> **Issue #11 status.** The OIDC implementation (Mode A) exists in the template and the
> workflow, and its static tests pass. It has **not** been tested against AWS: this account is an
> AWS Free Tier Project, and the organization's Service Control Policy denies `iam:*Provider*`,
> so no IAM identity provider can be created or even read here. Issue #11's OIDC acceptance
> criteria are therefore blocked in this account. Continuous deployment uses Mode B instead,
> which also needs no long-lived AWS credentials.

### Why this account can't use OIDC

AWS Free Tier Projects belong to an AWS organization with a Service Control Policy (SCP). Its
`DenyIAMRestrictedActions` statement denies `iam:*Provider*`. That covers
`iam:CreateOpenIDConnectProvider`, `iam:GetOpenIDConnectProvider` and
`iam:ListOpenIDConnectProviders`, which were confirmed as an explicit deny by the SCP in this
account. An SCP sets the maximum permissions for every principal in the account, including the
root user and roles with `AdministratorAccess`. No IAM policy in the account can override it. A
role trusting GitHub needs an `AWS::IAM::OIDCProvider`, so Mode A can't work here. That's why
the template creates no OIDC resources unless `GitHubDeployMode=oidc-ssm`, and the existing
stack stays updateable with its defaults.

### Mode B: self-hosted deploy runner (AWS Free Tier Projects)

A GitHub Actions runner on the instance itself picks up the `deploy-aws` job and deploys
locally. It connects out to GitHub over HTTPS, so there's no new inbound port, no SSH and no AWS
credential involved.

```
push to main
  └─ CI on GitHub-hosted runners: backend, backend-postgres, frontend, integration, e2e
       └─ "All checks passed"
            └─ deploy-aws (push to main of allfocusSS/SpendWise only; never pull requests)
                 runs-on: [self-hosted, linux, spendwise-deploy]  ── the runner on the instance
                 ├─ job-started hook: refuses any job but ci.yml / deploy-aws / push / main
                 ├─ skip if main has moved on (git ls-remote)
                 ├─ sudo -n /usr/local/sbin/spendwise-deploy-sha <github.sha>
                 │    └─ checks the SHA format and that it is the head of main, then
                 │       /usr/local/bin/spendwise-deploy <sha> as root
                 │       (fetch, build, docker compose up --wait; fails unless healthy)
                 └─ GET <PRODUCTION_URL>/api/health, /api/health/ready and / (bounded retries)
```

#### How the runner's privileges are limited

| Layer | What it enforces | File |
|---|---|---|
| Workflow | Only `deploy-aws` uses the `spendwise-deploy` label, only for a push to `main` of this repository after **All checks passed**. It has no `uses:` steps (no checkout, no third-party actions) and no `GITHUB_TOKEN` (`permissions: {}`). | `.github/workflows/ci.yml` |
| Job hook | `ACTIONS_RUNNER_HOOK_JOB_STARTED` runs before every job on this runner. Unless the event is `push`, the ref `refs/heads/main`, the repository this one, the workflow `ci.yml` on `main` and the job `deploy-aws`, the job fails before any step runs. This stops a pull request that edits the workflow to target the runner. | `runner/job-started.sh` |
| Linux user | The runner service runs as `spendwise-runner`: a system user with no password, `/sbin/nologin`, and no `docker`, `wheel` or `adm` group (membership in `docker` would be root-equivalent). | `runner/install-runner.sh` |
| sudo | Exactly one rule: `/usr/local/sbin/spendwise-deploy-sha` with one argument matching `^[0-9a-f]{40}$`, checked by sudo itself. No shells, no other commands, no `ALL`. | `runner/spendwise-runner.sudoers` |
| Wrapper | Root-owned. Rejects anything but exactly one 40-character lowercase SHA (exit 64). Refuses a SHA that isn't the current head of `main` (exit 65), so it can't deploy a branch, tag or pull request commit. Then runs `spendwise-deploy` with it. | `runner/spendwise-deploy-sha` |
| Network | An `iptables` owner-match rule rejects the runner user's traffic to the instance metadata service (169.254.169.254), so it can't obtain the instance role's credentials. Root, Docker and the SSM agent are unaffected. | `runner/spendwise-runner-no-imds.service` |
| Installer checks | Before it starts the runner, the installer verifies the isolation below and **refuses to start the runner if any check fails**. `install-runner.sh --verify` repeats the checks at any time. | `runner/install-runner.sh` |

The installer enforces and checks all of the following:

| Item | Required state |
|---|---|
| `/usr/local/sbin/spendwise-deploy-sha` (wrapper) | `root:root`, mode 0755. Neither the file nor its directory is writable by `spendwise-runner`. |
| `/usr/local/libexec/spendwise-runner-job-started` (hook) | `root:root`, mode 0755. Neither the file nor its directory is writable by `spendwise-runner`. |
| `/etc/sudoers.d/spendwise-runner` | `root:root`, mode 0440. Validated with `visudo -cf` before it's installed, and again in place. |
| Groups | `spendwise-runner` is not in `docker`, `wheel` or `adm` (removed if it was). |
| sudo | `spendwise-runner` can't run any other command with sudo. |
| `/srv/spendwise/secrets/spendwise.env` | Not readable by `spendwise-runner`: root-only, mode 0600, in a mode 0700 directory. |
| `/var/run/docker.sock` | Not readable or writable by `spendwise-runner`: `root:docker` 0660, and the user isn't in `docker`. Docker access would be root access. |
| Instance metadata | The `iptables` rule for `spendwise-runner` is in place. |

The Compose files and the checkout in `/opt/spendwise/src` are root-owned too, and the runner user
can't change them.

#### Public repository safety

GitHub recommends against self-hosted runners for public repositories: a pull request from a
fork could run code on them, and they aren't reset between jobs like GitHub-hosted runners.
This runner exists only because the AWS Free Tier Project SCP rules out Mode A. It relies on the
following controls; keep them all:

- Only the `deploy-aws` job, on a push to `main`, can use this runner. `pull_request` jobs and
  every CI job run on GitHub-hosted runners.
- **Untrusted pull request code must never execute on the production runner.** The workflow
  conditions keep the job off pull requests. The job hook enforces the same rule on the runner,
  even for a pull request that changes the workflow file.
- **Require a pull request and the "All checks passed" check for `main`** (branch protection),
  so a workflow change reaches `main` only after review.
- **Require approval before running workflows from fork pull requests** (repository Settings,
  Actions, General: require approval for all external contributors).
- Remaining risk: anyone who can push to `main` can change what `deploy-aws` runs, as
  `spendwise-runner`. That's still not root (sudo allows only the wrapper) and has no AWS
  credentials. Branch protection is what closes it.

#### Setting it up (once)

The runner is installed from a Session Manager shell on the instance (`SessionCommand` output).
Nothing here needs a stack update: the default template creates no deploy resources.

1. **GitHub settings.** Apply both settings from the [GitHub settings](#github-settings-for-both-modes)
   list below.
2. **Put the runner files on the instance.** After the change that adds `deploy/aws/runner/` is
   merged, deploy it once by hand. The installer runs from the root-owned checkout:

   ```bash
   sudo spendwise-deploy <commit SHA on main>        # or: sudo spendwise-deploy main
   ```

3. **Get a registration token on your machine.** It's valid for one hour, works for one
   registration, and is never stored:

   ```bash
   gh api -X POST repos/allfocusSS/SpendWise/actions/runners/registration-token --jq .token
   ```

4. **Run the installer on the instance** and paste the token when asked (it isn't echoed):

   ```bash
   sudo bash /opt/spendwise/src/deploy/aws/runner/install-runner.sh
   ```

   It does the following:
   - installs `libicu` and `iptables-nft`;
   - creates `spendwise-runner`;
   - installs the wrapper, the job hook, the sudo rule (after `visudo -cf` accepts it) and the
     metadata block;
   - downloads runner 2.338.2 and checks its SHA-256;
   - registers the runner as `spendwise-ec2` with the label `spendwise-deploy` (plus the
     default labels `self-hosted`, `Linux` and `X64`);
   - checks the runner user's isolation (the table above), and stops without starting the
     runner if any check fails;
   - starts it as a systemd service running as `spendwise-runner`;
   - prints `sudo -l` for that user.

   The token is used once and isn't written anywhere. The runner keeps only its own
   registration credentials, in `/opt/actions-runner`. Those identify this runner to GitHub;
   they are not a GitHub token.
5. **Set the repository variables** (variables, not secrets: nothing here is secret):

   ```bash
   gh variable set AWS_DEPLOY_MODE --body self-hosted-runner
   gh variable set PRODUCTION_URL  --body https://54.79.77.189.nip.io   # SiteUrl output, no trailing slash
   gh api repos/allfocusSS/SpendWise/actions/runners --jq '.runners[] | [.name, .status, (.labels | map(.name) | join(","))]'
   ```

The runner updates itself when GitHub releases a new version. Re-running the installer is safe;
it reinstalls the wrapper, hook, sudo rule and metadata block.

#### Removing the runner

```bash
# On your machine: pause deploys, then get a one-hour removal token
gh variable delete AWS_DEPLOY_MODE
gh api -X POST repos/allfocusSS/SpendWise/actions/runners/remove-token --jq .token

# On the instance (Session Manager)
cd /opt/actions-runner
sudo ./svc.sh stop && sudo ./svc.sh uninstall
sudo runuser -u spendwise-runner -- env HOME=/home/spendwise-runner ./config.sh remove --token <removal token>
sudo systemctl disable --now spendwise-runner-no-imds.service
sudo rm -f /etc/systemd/system/spendwise-runner-no-imds.service /etc/sudoers.d/spendwise-runner \
  /usr/local/sbin/spendwise-deploy-sha /usr/local/libexec/spendwise-runner-job-started
sudo rm -rf /opt/actions-runner /etc/systemd/system/actions.runner.*.service.d
sudo userdel -r spendwise-runner
sudo systemctl daemon-reload
```

If the instance is already gone, remove the runner on GitHub instead (Settings, Actions, Runners,
or `gh api -X DELETE repos/allfocusSS/SpendWise/actions/runners/<id>`).

### Mode A: GitHub OIDC and SSM (standard AWS accounts)

For an account without the Free Tier Project SCP. The `deploy-aws-oidc` job gets one-hour
credentials from GitHub's OIDC token and runs the deploy through SSM Run Command. There's no
runner on the instance.

```
push to main
  └─ CI ─► "All checks passed"
       └─ deploy-aws-oidc (push to main only; GitHub-hosted runner)
            ├─ GitHub OIDC token: aud sts.amazonaws.com,
            │    sub repo:allfocusSS@189591398/SpendWise@1441102769:ref:refs/heads/main
            ├─ STS AssumeRoleWithWebIdentity ─► GitHubDeployRole (1-hour credentials)
            ├─ ssm:SendCommand: document <stack>-deploy, CommitSha=<github.sha>, this instance only
            │    └─ on the instance, as root: spendwise-deploy <sha>
            ├─ ssm:GetCommandInvocation every 15 s, for at most about 53 minutes
            └─ GET <PRODUCTION_URL>/api/health, /api/health/ready and / (bounded retries)
```

#### Why no AWS keys

An access key in GitHub Secrets would be long-lived: it works from anywhere until someone
rotates it, and any workflow that can read the secret can use it. With OIDC, GitHub signs a token
for each job that describes which repository, branch and event it runs for. AWS STS exchanges it
for credentials that expire after one hour, and only if the role's trust policy accepts it. Only
the `deploy-aws-oidc` job gets `id-token: write`. Every other job keeps the read-only token.

#### Who can assume the role

The trust policy (`GitHubDeployRole` in `spendwise-stack.yaml`) allows only
`sts:AssumeRoleWithWebIdentity`, from the GitHub OIDC provider, with two exact
(`StringEquals`) conditions:

- `token.actions.githubusercontent.com:aud` = `sts.amazonaws.com`
- `token.actions.githubusercontent.com:sub` =
  `repo:allfocusSS@189591398/SpendWise@1441102769:ref:refs/heads/main`

This repository was created after 15 July 2026, so GitHub uses the **immutable subject format**:
the owner and repository names each carry their numeric ID (`@189591398`, `@1441102769`). The
older `repo:allfocusSS/SpendWise:...` form is not trusted. A repository that later takes over
the same name (after a rename, transfer or deletion) has a different ID and can't use the role.
To check the prefix GitHub uses:

```bash
gh api repos/allfocusSS/SpendWise/actions/oidc/customization/sub   # sub_claim_prefix
gh api repos/allfocusSS/SpendWise --jq '{repo_id: .id, owner_id: .owner.id}'
```

The IDs and branch are stack parameters (`GitHubOwnerId`, `GitHubRepositoryId`,
`GitHubDeployBranch`). Any other subject is refused: other repositories and forks, other branches
and tags, `pull_request` runs, and jobs that use a GitHub environment
(`...:environment:<name>`). That's why `deploy-aws-oidc` has no `environment:`.

Anyone who can push to `main` can trigger a deploy, so protect `main` (see [GitHub settings](#github-settings-for-both-modes)).

#### What the role can do

Only these two actions, nothing else:

| Action | Resource | Why |
|---|---|---|
| `ssm:SendCommand` | this instance's ARN and the `<stack>-deploy` document's ARN, both required | Start a deploy. |
| `ssm:GetCommandInvocation` | `*` | Read the deploy's status and output. This action has no resource-level permissions in IAM, so it can't be narrowed; it only reads results of commands already sent. |

The role doesn't use `AWS-RunShellScript`, which would let it run any command as root. The stack's
own Command document runs `/usr/local/bin/spendwise-deploy '{{ CommitSha }}'` and nothing else,
and SSM rejects any `CommitSha` that isn't 40 lowercase hex characters. The role has no EC2,
IAM or Session Manager permissions, no SSH, no `AdministratorAccess` and no managed policies.

#### Setting it up (once)

1. **Is there already a GitHub OIDC provider in the account?** An account can only have one
   per URL. If one for `token.actions.githubusercontent.com` is listed, pass its ARN as
   `ExistingGitHubOidcProviderArn`; the stack then uses it without owning it.

   ```bash
   export AWS_REGION=<region>
   aws iam list-open-id-connect-providers
   ```

2. **Update the stack in Mode A, reviewing the change set first.** Parameters you don't name keep
   their current values.

   ```bash
   aws cloudformation deploy --stack-name spendwise \
     --template-file deploy/aws/spendwise-stack.yaml \
     --capabilities CAPABILITY_IAM \
     --no-execute-changeset \
     --parameter-overrides GitHubDeployMode=oidc-ssm GitHubOwnerId=189591398 \
       GitHubRepositoryId=1441102769 GitHubDeployBranch=main \
       ExistingGitHubOidcProviderArn=""   # or the ARN from step 1

   # The command prints the change set's ARN. The only changes must be Adds:
   aws cloudformation describe-change-set --change-set-name <change set ARN> \
     --query 'Changes[].ResourceChange.[Action,LogicalResourceId,Replacement]' --output table
   #   Add  DeployDocument / GitHubDeployRole / GitHubOidcProvider   (nothing for Instance)
   aws cloudformation execute-change-set --change-set-name <change set ARN>
   aws cloudformation wait stack-update-complete --stack-name spendwise
   ```

3. **Store the outputs as GitHub repository variables:**

   ```bash
   out() { aws cloudformation describe-stacks --stack-name spendwise \
     --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }

   gh variable set AWS_DEPLOY_MODE     --body oidc-ssm
   gh variable set AWS_REGION          --body "$AWS_REGION"
   gh variable set AWS_DEPLOY_ROLE_ARN --body "$(out GitHubDeployRoleArn)"
   gh variable set AWS_INSTANCE_ID     --body "$(out InstanceId)"
   gh variable set AWS_DEPLOY_DOCUMENT --body "$(out DeployDocumentName)"
   gh variable set PRODUCTION_URL      --body "$(out SiteUrl)"
   ```

   The job checks these variables and fails with a clear message if one is missing.

### GitHub settings for both modes

- **Branch protection for `main`:** require a pull request and the status check **All checks
  passed** (Settings, Branches or Rules).
- **Fork pull requests:** require approval before their workflows run (Settings, Actions,
  General).

| Variable | Mode | Value |
|---|---|---|
| `AWS_DEPLOY_MODE` | both | `self-hosted-runner` or `oidc-ssm`; unset disables deploys |
| `PRODUCTION_URL` | both | `SiteUrl` output, no trailing slash, e.g. `https://54.79.77.189.nip.io` |
| `AWS_REGION` | A | the stack's region |
| `AWS_DEPLOY_ROLE_ARN` | A | output `GitHubDeployRoleArn` |
| `AWS_INSTANCE_ID` | A | output `InstanceId` |
| `AWS_DEPLOY_DOCUMENT` | A | output `DeployDocumentName` |

### How a deploy runs (both modes)

- **Trigger:** a push to `main` (including a merged pull request), after every CI job passed.
  Pull requests, other branches and manual runs never deploy.
- **The tested commit only:** the job deploys `github.sha`, never `main`. It then checks that
  `spendwise-deploy` reported deploying that exact SHA.
- **Newest commit wins:** if `main` has moved on by the time CI finishes, the job skips (with a
  notice) and the newer run deploys instead. In Mode B the wrapper refuses anything but the head
  of `main` as well. Deploys never overlap and are never cancelled half-way
  (`concurrency: deploy-aws-production`).
- **Bounded:** Mode B's deploy step times out after 50 minutes. Mode A polls SSM every 15
  seconds for at most about 53 minutes. Health checks retry a fixed number of times.
- **Failures:** the job fails if the deploy fails (the stack didn't become healthy), if it runs
  out of time, or if `/api/health`, `/api/health/ready` or `/` doesn't answer afterwards. The
  instance's output is in the job log. In Mode A, SSM returns at most 24,000 characters of it.
- A failed deploy leaves the previous containers running, unless the new ones had already
  replaced them (`docker compose up --wait` then reports them unhealthy).

### Checking it by hand

```bash
gh run list --workflow ci.yml --branch main --limit 5
gh run watch                                   # or: gh run view <run id> --log --job <job id>
curl -fsS https://54.79.77.189.nip.io/api/health/ready

# Mode B, on the instance (Session Manager)
systemctl status 'actions.runner.*' spendwise-runner-no-imds --no-pager
sudo -l -U spendwise-runner                    # only the wrapper, with a SHA
sudo bash /opt/spendwise/src/deploy/aws/runner/install-runner.sh --verify   # every check "ok"
sudo journalctl -u 'actions.runner.*' --since today   # includes refusals by the job hook

# Mode A, with your own credentials (and `out` from Mode A's step 3)
aws ssm list-commands --instance-id "$(out InstanceId)" --max-items 5 \
  --query 'Commands[].[CommandId,Status,Comment,RequestedDateTime]' --output table
aws cloudtrail lookup-events --max-results 5 \
  --lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRoleWithWebIdentity
```

### Redeploying and rolling back

- **Redeploy the same commit:** re-run the failed deploy job in GitHub (Re-run failed jobs). It
  deploys only if that commit is still the head of `main`.
- **Roll back:** revert the bad commit on `main` (`git revert`, pull request, merge). CI tests the
  revert and the deploy job ships it, like any other change.
- **Emergency rollback without CI:** open a Session Manager shell and run
  `sudo spendwise-deploy <older sha>` as an administrator. The runner can't do this, because its
  wrapper deploys only the head of `main`. In Mode A you can also send the deploy document for
  that SHA with your own credentials. The next push to `main` deploys `main` again, so follow it
  with a revert.
- **Pause automatic deploys:** `gh variable delete AWS_DEPLOY_MODE` (both jobs are then skipped).
  Set it again to resume.

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

**Continuous deployment.** Delete the GitHub variables **before** the stack, so pushes to `main`
skip the deploy instead of waiting for a runner, or a role, that no longer exists:

```bash
for v in AWS_DEPLOY_MODE PRODUCTION_URL AWS_DEPLOY_ROLE_ARN AWS_INSTANCE_ID AWS_DEPLOY_DOCUMENT AWS_REGION; do
  gh variable delete "$v"
done
```

In Mode B, also remove the runner from GitHub (see [Removing the runner](#removing-the-runner)).
Deleting the instance doesn't unregister it, so GitHub keeps listing it as offline.

In Mode A, deleting the stack deletes the deploy role and the deploy document. It also deletes
the GitHub OIDC provider **if this stack created it** (`ExistingGitHubOidcProviderArn` empty). Any other
role in the account that trusts that provider then stops working. If other stacks use it, create
the provider outside this stack and pass its ARN instead. A provider passed in that way is never
deleted by this stack.

## Checking the templates locally

Nothing here needs AWS credentials:

```bash
# CloudFormation schema and best practices
uvx cfn-lint deploy/aws/spendwise-stack.yaml deploy/aws/budget.yaml
# Free-tier and security guardrails, the deploy runner's files, and the deploy workflow
cd backend && uv run pytest tests/unit/test_aws_templates.py tests/unit/test_aws_runner.py \
  tests/unit/test_ci_workflow.py && cd ..
# Workflow syntax and its shell scripts (actionlint includes shellcheck; the runner's label is
# declared in .github/actionlint.yaml)
docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint:latest
```

The tests (part of the normal backend suite and CI) check, among other things:

- that no RDS, load balancer, NAT, ECS, EKS or other paid service is added;
- free-tier instance types and storage sizes;
- encrypted volumes and the retained data volume;
- that only ports 80 and 443 are open, and IMDSv2;
- the scope of the IAM permissions;
- that the first-boot script is valid bash with pinned, checksum-verified downloads;
- the budget's alerts;
- that Compose publishes only Caddy;
- that the default (Free Tier Project) mode creates no OIDC provider, role or document, and
  that `oidc-ssm` does;
- Mode A's deploy role: OIDC audience, a trust that matches only this repository's `main`
  (immutable subject), `AssumeRoleWithWebIdentity` only, `SendCommand` scoped to the deploy
  document and this instance, no administrator or wildcard permissions, and the outputs;
- Mode B's runner files:
  - the wrapper rejects anything but one 40-character lowercase SHA, and deploys only the head
    of `main`;
  - the sudo rule allows only the wrapper, with a SHA;
  - the job hook refuses pull requests, other refs, workflows, jobs and repositories, and fails
    closed;
  - the installer gives the runner user no route to root and keeps no GitHub token;
  - the metadata block is installed;
- the workflow:
  - only `deploy-aws` uses the self-hosted runner, and every CI job is GitHub-hosted;
  - deploys only on a push to `main` after "All checks passed", never for pull requests;
  - the exact commit SHA, the narrow sudo call only, and no AWS keys or secrets;
  - `id-token: write` only on the OIDC job;
  - bounded steps and the health checks.
