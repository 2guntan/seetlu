# Runbook — edge agent OTA (AC-F10-3)

1. Release: bump `__version__` in `edge/agent/seetlu_agent/__init__.py` (and `pyproject.toml`), merge, then
   `git tag agent-v<version> && git push origin agent-v<version>`. The `edge-image` workflow refuses a tag
   that does not match `__version__`, and pushes `ghcr.io/<owner>/seetlu-agent:<version>` (amd64 + arm64).
2. Pilot first: in the support console set the target version on **one** kit
   (`PUT /v1/support/kits/{id}/target-version`, audited `kit.target_version`).
3. The kit sees the new config within 30 s. The agent writes `SEETLU_AGENT_VERSION=<version>` into
   `/data/agent/.env` (the compose project file that the boot unit reads too), pulls, and recreates itself.
   If the pull fails the previous version is put back in `.env` and the command result says `failed`.
4. Check the next heartbeat (≤ 5 min) shows the new `agent_version`; the kit stays `ok` for 24 h.
5. Then the rest of the cohort, a few kits at a time. Each kit updates once per target version.

Roll back: set the target version back to the previous tag. Image pulls go over the shop's 4G: release
outside opening hours and avoid more than one release a week.
