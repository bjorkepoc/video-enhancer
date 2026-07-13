# Security Policy

## Supported Version

Security fixes are made on the latest commit of `main`. This project is still
pre-1.0 and does not promise fixes for older snapshots.

## Reporting A Vulnerability

Please use GitHub's private vulnerability reporting for this repository:

https://github.com/bjorkepoc/video-enhancer/security/advisories/new

Do not include a working exploit, private video URL, downloaded media, access
token, or personal data in a public issue. Include the affected commit, impact,
reproduction steps using synthetic data, and any proposed mitigation. A report
will be acknowledged as soon as practical; no fixed response-time SLA is
offered for this non-commercial pre-1.0 project.

## Security Boundary

The web UI is a local tool, not an internet-facing service. It must bind only to
loopback, use a process-specific temporary directory, and never be exposed with
a tunnel, reverse proxy, port-forward, container publish flag, or public host.
See [the launch and security checklist](docs/launch-privacy-security.md) for the
threat model and residual risks.
