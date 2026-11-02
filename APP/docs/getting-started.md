# Getting started

The single authoritative integrated startup procedure is maintained at the repository root:

- [Install and start Engine + Platform API + frontend](../../INSTALL.md)
- [Repository overview](../../README.md#quick-start)
- [Build, tests, and generated contracts](../../DEVELOPMENT.md)
- [Process and persistence boot sequence](../../BOOTSTRAP.md)

The Platform shell can run without the Engine, but `/readyz` will report degraded and Engine-backed
features will be unavailable. A clean clone can connect to Engine discovery; completing Agent chat
also requires a compatible reasoning adapter registered with the Engine.
