# AWS OIDC deployment verification

SpendWise production deployments from `main` are authenticated with a short-lived
GitHub Actions OIDC token and deploy the exact commit SHA that passed CI.

The production deployment gateway is exposed only through the existing HTTPS
endpoint and does not require long-lived AWS or GitHub credentials.
