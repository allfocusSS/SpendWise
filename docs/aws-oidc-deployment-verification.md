# AWS OIDC deployment verification

SpendWise production deployments are authenticated with a short-lived
GitHub Actions OIDC token and deploy the exact commit SHA that passed CI.

The production deployment gateway is exposed only through the existing HTTPS
endpoint and does not require long-lived AWS or GitHub credentials.

Since the change to manual promotion, the gateway accepts tokens only from the
**Promote Development to Production** workflow, run by hand on `main`, and no
longer from CI pushes. That commit must also already run in development. See
[Environments and promotion](environments.md).
