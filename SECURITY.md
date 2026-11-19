# Security Policy

## Scope and intended use

OT Sentinel Twin is an **isolated, educational and defensive** digital twin. All telemetry, assets, identities and
events are synthetic. The project:

* does not connect to PLCs, RTUs, gateways, historians or industrial networks;
* implements no industrial protocol and cannot command real equipment;
* is **not** a certified safety system and must not be used to protect a real process.

Please do not adapt it to interact with real industrial systems without appropriate authorisation, engineering review
and safety assessment.

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | yes |

## Reporting a vulnerability

Please report vulnerabilities **privately** using GitHub's *Report a vulnerability* (Security Advisories) on this
repository. Do not open public issues for security problems. Include the affected version, a description, reproduction
steps and impact. You can expect an acknowledgement within 7 days.

Examples of in-scope issues: authentication/authorisation bypass of read-only mode or the API token, cross-site
WebSocket hijacking, injection, path traversal in exports, denial of service that bypasses the documented limits,
container escape enablers in the provided images.

## Hardening summary

See [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): input validation,
restrictive CORS and WebSocket origin checks, body-size and rate limits, bounded buffers and retention, optional API
token, read-only demo mode, non-root read-only containers with all capabilities dropped, localhost-only ports,
dependency auditing, CodeQL and SHA-pinned CI actions. No secrets are stored in the repository.
