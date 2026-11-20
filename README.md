# Seetlu

Camera kit + service for small shops in Senegal and Côte d'Ivoire: every evening, one WhatsApp message
tells the owner whether the day's activity matched the day's money.

This repository starts as a **build pack**: specifications for Claude Code to build the whole system
end to end. Start with `CLAUDE.md`, then `docs/11-milestones.md`.

| Doc | Content |
| --- | --- |
| `CLAUDE.md` | Instructions, locked stack, conventions, rules, definition of done |
| `docs/01-product.md` | Features F1–F10 with acceptance criteria |
| `docs/02-architecture.md` | Components, flows, repo layout |
| `docs/03-data-model.sql` | PostgreSQL + TimescaleDB schema (first migration) |
| `docs/04-api.openapi.yaml` | API contract |
| `docs/05-edge-agent.md` | Frigate + seetlu-agent on the edge box |
| `docs/06-report-engine.md` | Metrics, verdict, moments, alerts |
| `docs/07-whatsapp.md` | Templates and inbound commands |
| `docs/08-apps.md` | Web app (owner, installer, support) and Android shop-phone app |
| `docs/09-security-privacy.md` | Legal frame, permissions, security |
| `docs/10-testing.md` | Simulator, scenarios, test layers |
| `docs/11-milestones.md` | Build order M0–M10 |
| `docs/12-human-tasks.md` | What a human must do in parallel |
| `docs/decisions.md` | Decision log (Claude Code appends to it) |

Product spec for humans: "Seetlu — Small-Shop Vision Kit: Product & Build Spec v1" (Claude doc).
