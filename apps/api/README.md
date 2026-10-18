# Prepared backend application image

Build context is the repository root; no `.env`, reference ZIP, browser profile or
host runtime directory is copied. The three reused projects install as wheels from
the checked-in sources under the existing lockfile. Runtime has no editable source
mount, global package manager, browser installer or model downloader.

Default command runs the API as UID/GID 10001. Reuse the image for the research worker
with `python -m skriller.research.runtime`, or retention with
`python -m skriller.retention_runtime`. Override/disable the API HTTP health check for
those non-HTTP services and use their existing worker heartbeat checks. Do not treat
API liveness as database/broker/worker readiness: use `/health/ready` for admission.

Inject deployment configuration/secrets at runtime. Configure the restricted
application database role, private storage and Firebase separately; run owner-level
bootstrap/migrations as a separate operator task. Never run schema bootstrap with
public API credentials or embed production secrets in the image.

Tokenizer/cleanup assets must be provisioned using the existing reviewed provisioning
scripts and mounted read-only when extraction is enabled. The base application image
has no browser, Docker CLI/socket, host account or platform session. Isolated browser
execution still requires its separate reviewed worker/egress controller deployment;
keep those operation settings disabled until that acceptance is complete.

This file is packaging preparation only. Image build, Linux dependency/runtime asset
closure, non-root filesystem permissions, readiness/restart, egress and hosted smoke
checks are **unverified**, deferred by the user until deployment. No container was
built or launched while adding it. Pin/check the build tool and base image manifests
for the selected host architecture during that deployment verification.
