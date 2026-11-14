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
   │            (and POST /_deploy to the deploy gateway's Unix socket on the host)
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
| `Caddyfile` | HTTPS and the reverse proxy, plus the `POST /_deploy` route to the deploy gateway. |
| `gateway/` | The deploy gateway (Mode B of [Automatic deploys](#automatic-deploys-from-github-actions)): the program, its installer, systemd units, root wrapper and sudo rule. |

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
- **Deploys from GitHub Actions:** no AWS access keys or other long-lived secrets exist (see
  [Automatic deploys](#automatic-deploys-from-github-actions)).
  - In this account (Mode B), a GitHub-hosted job sends a GitHub OIDC token to the deploy
    gateway on the instance, through Caddy on 443 (no new port). The gateway verifies the
    token's signature and exact claims, accepts each token once, and runs as an unprivileged
    user. That user may only run a root-owned wrapper through sudo, for the current head of
    `main`, and can't reach Docker, the database password or the instance metadata service.
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
commit (`github.sha`, never `main`). No AWS access key, GitHub token or other long-lived secret
exists anywhere, and every job runs on a GitHub-hosted runner. There are two ways to do it. The
repository variable `AWS_DEPLOY_MODE` chooses the workflow job, and the stack parameter
`GitHubDeployMode` chooses the AWS resources:

| | Mode B: GitHub OIDC → SpendWise deploy gateway | Mode A: GitHub OIDC → AWS IAM → SSM |
|---|---|---|
| For | **AWS Free Tier Projects (this account)**, whose SCP blocks `iam:*Provider*` | AWS accounts that permit IAM federation |
| `GitHubDeployMode` (stack) | `oidc-gateway` (the default) | `oidc-ssm` |
| `AWS_DEPLOY_MODE` (GitHub) | `oidc-gateway` | `oidc-ssm` |
| Workflow job | `deploy-aws`, GitHub-hosted | `deploy-aws-oidc`, GitHub-hosted |
| Who checks GitHub's token | the gateway on the instance (`deploy/aws/gateway/`) | AWS STS, through an IAM OIDC provider |
| AWS credentials used | none | one-hour role credentials |
| AWS resources for deploys | none | OIDC provider, deploy role, SSM document |
| How the instance is reached | `POST https://<site>/_deploy`, through Caddy on 443 | SSM Run Command |

With `AWS_DEPLOY_MODE` unset, neither job runs and nothing is deployed. Pull requests never
deploy in either mode.

> **Status (Issue #11).** Mode B is implemented and tested locally (token verification against
> locally generated keys, the host files on Amazon Linux 2023, Caddy's routing), but it has
> **not yet been installed on the instance, and no GitHub Actions deploy has run through it.**
> That needs the one-time installation below and a first real push to `main`. Mode A is
> implemented and its static tests pass, but it has **not** been tested against AWS: the SCP
> described below makes that impossible in this account.

### Why this account can't use AWS IAM OIDC

AWS Free Tier Projects belong to an AWS organization with a Service Control Policy (SCP). Its
`DenyIAMRestrictedActions` statement denies `iam:*Provider*`. That covers
`iam:CreateOpenIDConnectProvider`, `iam:GetOpenIDConnectProvider` and
`iam:ListOpenIDConnectProviders`, which were confirmed as an explicit deny by the SCP in this
account. An SCP sets the maximum permissions for every principal in the account, including the
root user and roles with `AdministratorAccess`: an explicit deny in an SCP can't be overridden by
any IAM policy in the account. A role trusting GitHub needs an `AWS::IAM::OIDCProvider`, so AWS
itself can't verify GitHub's tokens here. The template therefore creates no OIDC resources
unless `GitHubDeployMode=oidc-ssm`.

### Why not a self-hosted runner

The previous fallback, a persistent GitHub Actions runner on the instance, was abandoned:

- GitHub recommends against self-hosted runners for public repositories, and this one is public.
  It was only ever a constrained fallback.
- Registering it failed every time with `POST https://api.github.com/actions/runner-registration`
  → `HTTP 404 Not Found`, reproduced with a fresh repository registration token, runner 2.338.2,
  a completely clean `/opt/actions-runner` and no stale `.runner` or `.credentials` files.

Its files (`deploy/aws/runner/`) are gone. The instance may still have parts of the failed
bootstrap; [Cleaning up the abandoned runner](#cleaning-up-the-abandoned-runner) removes them.

### Mode B: GitHub OIDC deploy gateway (this account)

GitHub can sign a short-lived OIDC token for any job that has `id-token: write`, describing
exactly which repository, branch, event, workflow, runner and commit it runs for. Since AWS can't
check that token here, a small service on the instance does: the **deploy gateway**. It isn't
part of the SpendWise app or its login, and it shares nothing with them.

```
push to main
  └─ CI on GitHub-hosted runners: backend, backend-postgres, frontend, integration, e2e
       └─ "All checks passed"
            └─ deploy-aws (push to main of allfocusSS/SpendWise only; GitHub-hosted runner)
                 permissions: id-token: write (nothing else)
                 ├─ skip if main has moved on (git ls-remote)
                 ├─ OIDC token from GitHub, audience "spendwise-deploy" (masked, stdin only)
                 ├─ POST https://<site>/_deploy  {"sha", "run_id", "run_attempt"}
                 │    Caddy :443 ─► Unix socket ─► spendwise-deploy-gateway (no network port)
                 │       ├─ RS256 signature with GitHub's published keys; exp, nbf, iat, iss, aud
                 │       ├─ exact claims: repository + IDs, main, push, ci.yml, GitHub-hosted,
                 │       │  sha / run_id / run_attempt equal to the body
                 │       ├─ token ID (jti) not used before (SQLite)
                 │       ├─ no other deploy running ─► 202 "running"
                 │       └─ in the background: sudo -n /usr/local/sbin/spendwise-deploy-sha <sha>
                 │            └─ as root: deploy lock, head of main?, then
                 │               spendwise-deploy <sha> (fetch, build, compose up --wait), ≤ 50 min
                 │            then GET https://<site>/api/health/ready
                 ├─ every 20 s: POST again with a fresh token ─► "running" … "success"
                 └─ GET <PRODUCTION_URL>/api/health, /api/health/ready and / (bounded retries)
```

**Why start-then-poll rather than one long request:** building the image on a micro instance
takes 20 to 45 minutes. An HTTPS request that stays silent that long, across the internet from
a GitHub-hosted runner, is easily cut off by idle timeouts along the way. So the first request
starts the deploy and returns at once, and the job asks for its status every 20 seconds. Each
of those requests is authenticated the same way, with its own fresh token. There's no
unauthenticated status endpoint.

#### The token: exact claims required

The issuer is fixed in the program: `https://token.actions.githubusercontent.com`. The other
values are in `deploy/aws/gateway/deploy-gateway.env`, confirmed with GitHub:

```bash
gh api repos/allfocusSS/SpendWise --jq '{id, owner_id: .owner.id}'      # 1441102769, 189591398
gh api repos/allfocusSS/SpendWise/actions/oidc/customization/sub        # use_immutable_subject: true
```

| Claim | Required value |
|---|---|
| `iss` | `https://token.actions.githubusercontent.com` (exactly) |
| `aud` | `spendwise-deploy` (exactly; a list is refused) |
| `sub` | `repo:allfocusSS@189591398/SpendWise@1441102769:ref:refs/heads/main` (GitHub's immutable subject format, with the owner and repository IDs) |
| `repository` | `allfocusSS/SpendWise` |
| `repository_id` | `1441102769` |
| `repository_owner_id` | `189591398` |
| `ref` / `ref_type` | `refs/heads/main` / `branch` |
| `event_name` | `push` |
| `runner_environment` | `github-hosted` |
| `workflow_ref` | `allfocusSS/SpendWise/.github/workflows/ci.yml@refs/heads/main` |
| `sha`, `run_id`, `run_attempt` | equal to the request body's `sha`, `run_id`, `run_attempt` |
| `jti` | present, not empty, never used before |
| `exp`, `nbf`, `iat` | present and valid, with 60 s of clock skew; `iat` within the last 10 minutes |

The repository name alone never authorizes anything: a renamed, transferred or re-created
repository has another ID. Pull requests (`event_name`, `ref` and `sub` differ), tags, other
branches, forks (another repository ID), other workflows, `workflow_dispatch` runs and tokens
from self-hosted runners are all refused, even if a pull request edits the workflow file.

#### How the token is verified

- **Library:** [PyJWT](https://pyjwt.readthedocs.io/) 2.15.1 with `cryptography` for RSA, the
  gateway's only third-party packages. They're installed from `requirements.txt`, which pins
  every file by its SHA-256 (`pip install --require-hashes --only-binary :all:`). The standard
  library has no JWT or RSA verification, and writing signature checks by hand is exactly what
  the task should avoid.
- **Keys:** from GitHub's OpenID discovery document
  (`https://token.actions.githubusercontent.com/.well-known/openid-configuration`), then its
  `jwks_uri`. Both are fetched over verified HTTPS, without following redirects. Discovery must
  name the same issuer, and `jwks_uri` must be an HTTPS URL on the issuer's host. Nothing is
  hardcoded.
- **Algorithm:** `RS256` only, and only while discovery advertises it. `alg: none`, every HMAC
  (`HS*`) algorithm, `RS512`, `PS256`, `ES256` and tokens without a `kid` are refused before any
  key is used. The key is chosen by `kid` and must be an RSA signing key.
- **Caching and rotation:** keys are cached for an hour. An unknown `kid` fetches them again,
  at most once a minute, so GitHub's key rotation keeps working and junk tokens can't make the
  gateway hammer GitHub.
- **Failing closed:** if discovery or the keys can't be fetched or used, nothing is accepted
  (`503 unavailable`), and the old keys aren't used after a failed refresh either.

#### Replay protection

Each token is accepted for exactly one request. After a token passes verification, the gateway
inserts a SHA-256 of its `jti` into SQLite (`/var/lib/spendwise-deploy-gateway/gateway.sqlite3`,
owned by the gateway, mode 0700 directory). The primary key makes the insert fail for a token ID
already there. That holds for simultaneous requests too, and across restarts. Next to the hash it
stores the expiry, time used, run ID, attempt and SHA, never the token. Rows are deleted one day
after the token expired. A replayed token gets `409 replay_rejected`.

#### Exact SHA

- The workflow sends `${{ github.sha }}`, which the token's `sha` claim must match. A caller
  can't choose a commit the token doesn't vouch for.
- The SHA must be exactly 40 lowercase hex characters, checked by the gateway, by sudo's rule
  and again by the wrapper.
- The wrapper refuses a SHA that isn't the current head of `main` (`superseded`), so an old
  run can't roll production back.

#### One deploy at a time, and bounded

- The gateway's database allows only one `running` deploy (a partial unique index). Another
  run gets `409 busy`.
- The root wrapper also takes a host lock, `flock` on `/run/spendwise-deploy.lock`, and exits
  with `busy` if it's held. A manual deploy through the wrapper takes the same lock.
- The workflow's `concurrency: deploy-aws-production` serializes the jobs as well.
- The wrapper stops `spendwise-deploy` after 50 minutes (`timeout`, then `KILL` a minute
  later). The gateway has its own backstop a minute after that.
- The workflow polls for at most 55 minutes, and its job times out after 65.
- The deploy runs in the background, so a client that disconnects changes nothing. If the
  gateway itself is restarted mid-deploy, systemd stops the deploy with it, and the run is
  reported as `interrupted`.
- Output is bounded: the first 16 KiB and last 48 KiB of the wrapper's output, with tokens,
  private keys, `…PASSWORD=`/`…SECRET=`/`…TOKEN=` values and URL passwords redacted. It's
  written to `/var/lib/spendwise-deploy-gateway/logs/deploy-<run>-<attempt>.log` (mode 0600; the
  last 30 are kept). It is **never** returned to GitHub.

#### Answers

All answers are small JSON objects: `{"status": …}`. The deploy's own status also has `sha`,
`run_id`, `run_attempt`, `started_at`, `finished_at` and `exit_code`. They never include the
token, its claims or the deploy's output.

| HTTP | `status` | Meaning |
|---|---|---|
| 202 | `running` | Deploy started, or still running. |
| 200 | `success` | Deployed, `spendwise-deploy` reported this SHA, and `/api/health/ready` answered. |
| 200 | `deploy_failed` | `spendwise-deploy` failed, or didn't report this SHA. |
| 200 | `health_failed` | Deployed, but `/api/health/ready` didn't answer 200. |
| 200 | `timeout` | Stopped after 50 minutes. |
| 200 | `superseded` | Not the head of `main` any more; the newer run deploys (the job ends without error). |
| 200 | `busy` / `interrupted` | The host lock was held, or the gateway restarted mid-deploy. |
| 400 | `invalid_sha` / `invalid_request` | Malformed body. |
| 401 | `unauthorized` | Any token problem. The reason is only in the gateway's journal. |
| 405 / 404 / 411 / 413 / 415 | … | Not `POST /_deploy`, no length, body over 1 KiB (Caddy: over 4 KB), not JSON. |
| 409 | `replay_rejected` / `busy` | Token already used / another run's deploy is running. |
| 503 | `unavailable` | GitHub's keys couldn't be fetched (fails closed). |

The job fails on anything but `success` (or `superseded`). It retries only transport failures,
502, 503 and 504, at most 15 times in a row; Caddy itself may restart during a deploy.

#### Network isolation

- **No new port.** The gateway listens only on a Unix socket,
  `/run/spendwise-deploy-gateway/gateway.sock`, never on TCP. The security group still allows
  only 80 and 443, and Compose still publishes only Caddy's 80 and 443.
- **Caddy is the only way in.** `compose.aws.yaml` bind-mounts the socket's directory into the
  Caddy container, read-only (connecting to a socket needs no write access to the mount). The
  directory is the gateway's, mode 0750, created at every boot by a `tmpfiles.d` entry before
  Docker starts. Only the gateway and root can use it; Caddy runs as root in its container.
- **The Caddy route** (`deploy/aws/Caddyfile`):
  - only exactly `/_deploy` is forwarded, and only `POST`, with a body of at most 4 KB;
  - another method gets `405` with `Allow: POST`, and anything under `/_deploy/` gets `404`;
  - none of it ever reaches the app, and every other path is routed as before;
  - upstream timeouts are 5 s to connect and 60 s for the answer;
  - there's no access log, and Caddy never logs `Authorization` headers anyway.
- **Why not a TCP port:** a deploy service on `0.0.0.0:<port>` would be one security group
  mistake away from the internet. A private Docker-bridge listener would need its own firewall
  rules. The Unix socket needs neither.
- Caddy matches paths case-insensitively, so `/_DEPLOY` reaches the gateway too. The gateway
  answers anything but exactly `/_deploy` with `404`.

#### The gateway's privileges

The gateway runs as `spendwise-deploy-gateway`, a systemd service (`spendwise-deploy-gateway`).
Its one privileged operation is `sudo -n /usr/local/sbin/spendwise-deploy-sha <sha>`. The
installer enforces each item below. It refuses to start the gateway unless every check passes,
and `install-gateway.sh --verify` repeats the checks at any time:

| Item | Required state |
|---|---|
| User | Not root; no password; shell `/sbin/nologin`; no home directory. |
| Groups | Not in `docker`, `wheel` or `adm` (removed if it was). `docker` would be root-equivalent. |
| Service | `User=spendwise-deploy-gateway`; requires the metadata block below. |
| sudo | Exactly one rule (`/etc/sudoers.d/spendwise-deploy-gateway`, `root:root` 0440, `visudo -cf` before installing and in place): the wrapper with one argument matching `^[0-9a-f]{40}$`, checked by sudo itself. No shells, no `ALL`, no other command or argument. No other sudo rule may mention the wrapper. |
| Wrapper | `/usr/local/sbin/spendwise-deploy-sha`, root-owned. It checks the SHA again, takes the deploy lock, refuses anything but the head of `main`, and runs `spendwise-deploy <sha>` with a time limit and a normal umask. |
| Root-owned files | The program, its virtual environment, its settings, the units, the `tmpfiles.d` entry, the wrapper, the sudo rule, `/usr/local/bin/spendwise-deploy` and `/etc/spendwise/deploy.env` (which the wrapper reads as root) are all `root:root` and not group- or world-writable. The gateway user can't write any of them, or their directories. |
| Secrets | Can't read `/srv/spendwise/secrets/spendwise.env`. |
| Docker | Can't read or write `/var/run/docker.sock`, `/run/docker.sock` or `/run/containerd/containerd.sock`. |
| Instance metadata | An `iptables` owner-match rule rejects its traffic to 169.254.169.254, so it can't get the instance role's credentials. Root, and so `spendwise-deploy`, isn't affected. |
| Socket directory | `/run/spendwise-deploy-gateway`, owned by the gateway, mode 0750. |

The service doesn't use `NoNewPrivileges=` or systemd's file-system sandboxing. The first would
stop sudo, and the second would also confine the root deploy, which runs inside the same unit.
The checks above provide the user's isolation instead.

#### Threat model

| Threat | What stops it |
|---|---|
| Anyone on the internet calls `/_deploy` | Without a valid GitHub-signed token for this repository's `main` push, the answer is `401` and nothing runs. Unknown key IDs refresh GitHub's keys at most once a minute. |
| A pull request, including one from a fork, edits the workflow to get a token | Its token says `pull_request`, another `ref` and `sub`, and for a fork another repository ID: refused. |
| Another repository, workflow or job asks for audience `spendwise-deploy` | Repository, IDs, `sub` and `workflow_ref` must all match exactly. |
| A runner someone else controls | `runner_environment` must be `github-hosted`. |
| A token is replayed, or sent twice at once | Each `jti` works once (SQLite primary key). |
| A token is stolen from a run | It's masked in logs and passed on stdin only. It expires within minutes, works once, and only for that run's own commit, which must still be the head of `main`. The workflow uses each token right away. |
| Rolling production back to an old commit | The `sha` claim must equal the request, and the wrapper deploys only the head of `main`. |
| Code execution as the gateway user | It can only run the wrapper for the head of `main`. No Docker, no secrets, no instance metadata, no other sudo, no writable program or configuration file. |
| GitHub's key documents are tampered with | Verified HTTPS, no redirects, the discovery issuer must match, and `jwks_uri` must be on the issuer's host. Any failure fails closed. |
| Floods and oversized requests | Bodies over 4 KB are dropped by Caddy (and over 1 KiB by the gateway); connections time out after 15 s; one deploy at a time. |

What remains:
- **Anyone who can push to `main` decides what gets deployed.** That is the intended trust;
  branch protection is what limits it.
- **GitHub is trusted** as the token issuer.
- **The gateway is reachable from the internet** through Caddy. That's the price of running no
  inbound tunnel, and it's why every request is authenticated.
- **Restarting the gateway stops a running deploy.** The installer refuses to restart it while
  the deploy lock is held.

#### Installing it on the existing instance (once)

Nothing here replaces the instance, opens a port or needs a stack update. The current
production app keeps running throughout.

1. **Merge this change with `AWS_DEPLOY_MODE` unset.** It is unset now (`gh variable list`
   shows no variables), so the merge deploys nothing. Apply the
   [GitHub settings](#github-settings-for-both-modes).
2. **Open a shell on the instance** (`SessionCommand` output) and
   [clean up the abandoned runner](#cleaning-up-the-abandoned-runner).
3. **Deploy the merged commit by hand.** This gives Caddy the `/_deploy` route and the socket
   mount, and puts the gateway's files in the root-owned checkout:

   ```bash
   sudo spendwise-deploy <commit SHA of the merge on main>
   ```

4. **Install the gateway** from that checkout. It needs no token or secret:

   ```bash
   sudo bash /opt/spendwise/src/deploy/aws/gateway/install-gateway.sh
   ```

   It does the following:
   - installs `python3.13` and `iptables-nft`;
   - creates `spendwise-deploy-gateway`;
   - installs the program and its hash-pinned packages, root-owned;
   - writes `/etc/spendwise/deploy-gateway.env`, adding the health URL from `deploy.env`;
   - installs the wrapper and the sudo rule (after `visudo -cf`), the metadata block, the
     socket directory and the service;
   - checks the isolation (the table above), and won't start the gateway if any check fails;
   - checks the settings and GitHub's keys as the gateway user (`--check`);
   - starts the gateway;
   - prints `sudo -l` for its user.

5. **Check it:**

   ```bash
   sudo bash /opt/spendwise/src/deploy/aws/gateway/install-gateway.sh --verify   # every line "ok"
   curl -s -X POST https://54.79.77.189.nip.io/_deploy -H 'Content-Type: application/json' \
     --data '{"sha":"0000000000000000000000000000000000000000","run_id":"1","run_attempt":"1"}'
   # {"status": "unauthorized"}: Caddy reached the gateway, which refused the missing token
   curl -s -o /dev/null -w '%{http_code}\n' https://54.79.77.189.nip.io/_deploy   # 405
   ```

6. **Turn deploys on** (repository variables, not secrets: nothing here is secret):

   ```bash
   gh variable set AWS_DEPLOY_MODE --body oidc-gateway
   gh variable set PRODUCTION_URL  --body https://54.79.77.189.nip.io   # SiteUrl output, no trailing slash
   ```

7. **The first real deploy** is the next push to `main`. Watch the job, and on the instance
   `sudo journalctl -fu spendwise-deploy-gateway`. Only after it succeeds is Mode B verified in
   production.

Re-running the installer is safe (it reinstalls every file). It refuses to restart the gateway
while a deploy holds the lock.

#### A replacement instance

A new stack's first boot deploys the app as before. It doesn't install the gateway: changing
the instance's first-boot script would make CloudFormation stop and start the running instance.
After the stack is created, run step 4 (and 5) in a Session Manager shell. Then update
`PRODUCTION_URL` if the address changed. Nothing changes on GitHub's side: the gateway trusts
the same repository IDs and needs no registration.

#### Cleaning up the abandoned runner

The failed runner bootstrap may have left some of these on the instance. Remove only these.
Don't touch `/opt/spendwise/src`, the containers, `/srv/spendwise` (database, certificates,
password), Caddy, `/usr/local/bin/spendwise-deploy` or `/usr/local/sbin/spendwise-deploy-sha`:
the gateway reuses the wrapper, and its installer replaces it with the new version.

```bash
# On the instance (Session Manager). Each command is safe if the item doesn't exist.
ls -ld /opt/actions-runner /etc/sudoers.d/spendwise-runner /usr/local/libexec/spendwise-runner-job-started \
  /etc/systemd/system/spendwise-runner-no-imds.service /etc/systemd/system/actions.runner.* 2> /dev/null
id spendwise-runner

# The runner service, if `svc.sh install` ever ran (registration failed, so normally it didn't)
if [ -f /opt/actions-runner/.service ]; then
  (cd /opt/actions-runner && sudo ./svc.sh stop; sudo ./svc.sh uninstall)
fi
sudo rm -rf /etc/systemd/system/actions.runner.*.service.d

# The runner user's metadata block: stop it while the user still exists (its stop command
# names the user), then remove it
sudo systemctl disable --now spendwise-runner-no-imds.service 2> /dev/null || true
sudo rm -f /etc/systemd/system/spendwise-runner-no-imds.service
sudo systemctl daemon-reload

# The runner's sudo rule and job hook (not the wrapper: the gateway reuses it)
sudo rm -f /etc/sudoers.d/spendwise-runner /usr/local/libexec/spendwise-runner-job-started
sudo visudo -c

# The runner's user and its files
sudo pkill -u spendwise-runner 2> /dev/null || true
id spendwise-runner > /dev/null 2>&1 && sudo userdel -r spendwise-runner
sudo rm -rf /opt/actions-runner

# Nothing left over: no rule for the old user, and no leftover runner on GitHub
sudo iptables -S OUTPUT | grep -c 169.254.169.254         # 0 before the gateway is installed
gh api repos/allfocusSS/SpendWise/actions/runners --jq '.total_count'   # on your machine: 0
```

Registration never succeeded, so GitHub should list no runner. If it lists `spendwise-ec2`,
delete it in Settings, Actions, Runners. The gateway's `--verify` fails while any other sudo
rule (such as the old runner's) still mentions the wrapper.

#### Troubleshooting

| Symptom | Where to look |
|---|---|
| The job reports `unauthorized` | `sudo journalctl -u spendwise-deploy-gateway` names the failing check (e.g. `claim workflow_ref does not match`). The repository was renamed or transferred (new IDs), `ci.yml` was renamed, or the OIDC subject customization changed. Compare with `deploy-gateway.env` and re-run the installer after updating it. |
| `unavailable` (503) | The gateway can't fetch GitHub's keys. Run the installer's `--check` line by hand, and check outbound HTTPS. |
| No answer, or 502 from Caddy, for a long time | `systemctl status spendwise-deploy-gateway`; `sudo ls -la /run/spendwise-deploy-gateway` (socket present?). If Caddy started before the directory existed, recreate it: `$c up -d --force-recreate caddy` (see [Operating it](#operating-it)). |
| `busy` | A deploy holds the lock: `sudo flock -n /run/spendwise-deploy.lock true || echo held`. Wait for it, then re-run the job. |
| `deploy_failed`, `timeout` or `health_failed` | `sudo ls -t /var/lib/spendwise-deploy-gateway/logs/` and the newest `deploy-<run>-<attempt>.log`; `$c ps`; `$c logs --tail 100 app`. The health check is made from the instance to its own public URL. |
| `interrupted` | The gateway restarted mid-deploy. Re-run the job: a new attempt is a new deploy. |
| `replay_rejected` | A token was sent twice, which the workflow never does. Check for a modified workflow. |

#### Removing the gateway

```bash
gh variable delete AWS_DEPLOY_MODE                       # on your machine: pause deploys first
# On the instance
sudo systemctl disable --now spendwise-deploy-gateway.service spendwise-deploy-gateway-no-imds.service
sudo rm -f /etc/systemd/system/spendwise-deploy-gateway{,-no-imds}.service \
  /etc/tmpfiles.d/spendwise-deploy-gateway.conf /etc/sudoers.d/spendwise-deploy-gateway \
  /etc/spendwise/deploy-gateway.env
sudo rm -rf /usr/local/lib/spendwise-deploy-gateway /var/lib/spendwise-deploy-gateway /run/spendwise-deploy-gateway
sudo systemctl daemon-reload && sudo visudo -c
sudo userdel spendwise-deploy-gateway
```

Caddy then answers `502` on `/_deploy` until a deploy without the route ships. The rest of the
site is unaffected.

### Mode A: GitHub OIDC and SSM (AWS accounts that permit federation)

For an account without the Free Tier Project SCP. This is the standard production
recommendation: nothing on the instance accepts requests from GitHub. The `deploy-aws-oidc` job
gets one-hour credentials from GitHub's OIDC token and runs the deploy through SSM Run Command.

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
the two deploy jobs get `id-token: write`. Every other job keeps the read-only token.

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
| `AWS_DEPLOY_MODE` | both | `oidc-gateway` (this account) or `oidc-ssm`; unset disables deploys |
| `PRODUCTION_URL` | both | `SiteUrl` output, no trailing slash, e.g. `https://54.79.77.189.nip.io`. In Mode B the deploy endpoint is derived from it: `<PRODUCTION_URL>/_deploy` |
| `AWS_REGION` | A | the stack's region |
| `AWS_DEPLOY_ROLE_ARN` | A | output `GitHubDeployRoleArn` |
| `AWS_INSTANCE_ID` | A | output `InstanceId` |
| `AWS_DEPLOY_DOCUMENT` | A | output `DeployDocumentName` |

Mode B needs no secret and no other variable. Its OIDC audience, `spendwise-deploy`, is fixed in
the workflow and in `deploy/aws/gateway/deploy-gateway.env` (a test checks they match), because
changing it on one side only would just break deploys.

### How a deploy runs (both modes)

- **Trigger:** a push to `main` (including a merged pull request), after every CI job passed.
  Pull requests, other branches and manual runs never deploy.
- **The tested commit only:** the job deploys `github.sha`, never `main`. `spendwise-deploy` must
  report deploying that exact SHA (checked by the gateway in Mode B, by the job in Mode A).
- **Newest commit wins:** if `main` has moved on by the time CI finishes, the job skips (with a
  notice) and the newer run deploys instead. In Mode B the wrapper refuses anything but the head
  of `main` as well. Deploys never overlap and are never cancelled half-way
  (`concurrency: deploy-aws-production`, plus the gateway's and the host's locks in Mode B).
- **Bounded:** in Mode B the wrapper stops a deploy after 50 minutes and the job polls for at
  most 55. Mode A polls SSM every 15 seconds for at most about 53 minutes. Health checks retry a
  fixed number of times.
- **Failures:** the job fails if the deploy fails (the stack didn't become healthy), if it runs
  out of time, or if `/api/health`, `/api/health/ready` or `/` doesn't answer afterwards. In
  Mode B only the status reaches the job log; the instance's output stays on the instance
  (`/var/lib/spendwise-deploy-gateway/logs/`). In Mode A, SSM returns at most 24,000 characters
  of it to the job log.
- A failed deploy leaves the previous containers running, unless the new ones had already
  replaced them (`docker compose up --wait` then reports them unhealthy).

### Checking it by hand

```bash
gh run list --workflow ci.yml --branch main --limit 5
gh run watch                                   # or: gh run view <run id> --log --job <job id>
curl -fsS https://54.79.77.189.nip.io/api/health/ready

# Mode B, on the instance (Session Manager)
systemctl status spendwise-deploy-gateway spendwise-deploy-gateway-no-imds --no-pager
sudo -l -U spendwise-deploy-gateway            # only the wrapper, with a SHA
sudo bash /opt/spendwise/src/deploy/aws/gateway/install-gateway.sh --verify   # every check "ok"
sudo journalctl -u spendwise-deploy-gateway --since today   # deploys, and why requests were refused
sudo python3 -c 'import sqlite3; [print(*r) for r in sqlite3.connect("/var/lib/spendwise-deploy-gateway/gateway.sqlite3").execute("SELECT run_id, run_attempt, sha, status, exit_code FROM deployments ORDER BY started_at DESC LIMIT 5")]'

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
- **Emergency rollback without CI:** open a Session Manager shell and, as an administrator, run
  `sudo flock -n /run/spendwise-deploy.lock spendwise-deploy <older sha>` (the lock keeps it from
  overlapping an automatic deploy). The gateway can't do this, because its wrapper deploys only
  the head of `main`. In Mode A you can also send the deploy document for that SHA with your own
  credentials. The next push to `main` deploys `main` again, so follow it with a revert.
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
skip the deploy instead of failing against a gateway, or a role, that no longer exists:

```bash
for v in AWS_DEPLOY_MODE PRODUCTION_URL AWS_DEPLOY_ROLE_ARN AWS_INSTANCE_ID AWS_DEPLOY_DOCUMENT AWS_REGION; do
  gh variable delete "$v"
done
```

In Mode B there's nothing to remove on GitHub's or AWS's side: the gateway lives only on the
instance, and nothing was registered anywhere.

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
# Free-tier and security guardrails, the deploy gateway and its host files, and the workflow
cd backend && uv run pytest tests/unit/test_aws_templates.py tests/unit/test_deploy_gateway.py \
  tests/unit/test_aws_gateway_host.py tests/unit/test_ci_workflow.py && cd ..
# Workflow syntax and its shell scripts (actionlint includes shellcheck)
docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint:latest
# The gateway's shell scripts
docker run --rm -v "$PWD":/mnt -w /mnt koalaman/shellcheck:stable \
  deploy/aws/gateway/install-gateway.sh deploy/aws/gateway/spendwise-deploy-sha
# The Caddyfile
docker run --rm -e SPENDWISE_SITE_ADDRESS=example.com -v "$PWD/deploy/aws/Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2.11 caddy validate --config /etc/caddy/Caddyfile
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
- that Compose publishes only Caddy, and that Caddy reaches the gateway only for `POST /_deploy`,
  through the read-only socket mount;
- Mode B's gateway, with locally generated RSA keys and a fake issuer (never GitHub's):
  - a valid token is accepted; wrong key, unknown `kid`, bad signature, `alg: none`, HMAC and
    other algorithms, wrong issuer or audience, expired, not yet valid or implausible `iat`, and
    every wrong claim (subject, repository, IDs, branch, tag, pull request, self-hosted runner,
    workflow, SHA, run) are refused;
  - key rotation and refresh limits, and failing closed when discovery or keys are unusable;
  - each `jti` works once, also for simultaneous requests and after a restart;
  - one deploy at a time; the wrapper's results, time limit, bounded and redacted output, and
    the health check; that tokens never reach the logs;
  - the HTTP side: `POST /_deploy` only, the size limit, the socket's permissions;
- the gateway's host files:
  - the wrapper accepts only one 40-character lowercase SHA, takes the lock, deploys only the
    head of `main`, and resets the umask;
  - the sudo rule allows only the wrapper, with a SHA;
  - the installer's isolation checks run before the gateway starts;
  - packages are hash-pinned, and the units run unprivileged behind the metadata block;
- the workflow:
  - every job is GitHub-hosted, and no self-hosted runner remains;
  - deploys only on a push to `main` after "All checks passed", never for pull requests;
  - the gateway job gets only `id-token: write`, requests its own token with the gateway's
    audience, masks it and never puts it on a command line;
  - the exact commit SHA and run, and no AWS keys, tokens or secrets;
  - bounded polling and the health checks.
