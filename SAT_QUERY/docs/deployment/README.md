# Deployment status and local operation

SatQuery currently ships a locally runnable FastAPI application, browser
workspace, and CLI. The repository does not include a production deployment
configuration. No Docker image, Kubernetes manifests, Terraform, cloud
provisioning, managed database, ingress, authentication/authorization layer,
tenant isolation, secret manager, backup automation, or service-level
objective is supplied.

## Supported local operation

Use the [setup guide](../development/SETUP.md) to install and run the app.
The server binds to loopback (`127.0.0.1:8000`) by default. Connector
configuration is opt-in. Keep the service on a trusted local machine unless
the owner supplies and configures network access controls and authentication.

Optional SQLite paths provide single-host persistence for selected platform
records. Configure and back up those databases according to local operational
requirements. SQLite does not provide multi-host coordination, encryption at
rest, disaster recovery, or provider-side idempotency. The default in-memory
stores are lost when the process exits.

## Before exposing a deployment

The repository alone does not define the required deployment architecture or
security posture. An operator must choose the hosting environment, user
identity provider, authorization model, secret delivery mechanism, allowed
connector endpoints, data retention policy, storage/backup objectives,
network exposure, licensing obligations, resource limits, and operational
monitoring. These are owner/operator decisions; a `production` config profile
does not provision or secure infrastructure.

Do not infer production readiness from a successful local run or CI test.
There is no supported public multi-user deployment profile today.
