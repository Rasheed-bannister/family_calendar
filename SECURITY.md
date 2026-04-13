# Security Policy

## Supported Versions

Family Calendar is a small, single-maintainer project. Only the latest release receives security fixes.
| Version  | Supported          |
| -------- | ------------------ |
| 0.2.9    | :white_check_mark: |
| < 0.2.9  | :x:                |

If you're running an older version, please upgrade before reporting — the issue may already be fixed on `main`.

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security reports.**

Use GitHub's private vulnerability reporting instead:

1. Go to the [Security tab](https://github.com/Rasheed-bannister/family_calendar/security) of this repository.
2. Click **Report a vulnerability**.
3. Fill in the advisory form with as much detail as you can.

If you'd rather email, you can reach the maintainer at the address on the GitHub profile ([@Rasheed-bannister](https://github.com/Rasheed-bannister)). Please include **"family_calendar security"** in the
subject line.

### What to include

- A clear description of the issue and its impact.
- Steps to reproduce (ideally a minimal proof of concept).
- The version / commit you tested against.
- Any suggested remediation, if you have one in mind.

### What to expect

- **Acknowledgement**: within 3 business days.
- **Initial assessment**: within 7 business days.
- **Fix + release**: depends on severity and complexity — typically within 2–4 weeks for high-severity issues.

I will keep you updated throughout and credit you in the release notes unless you'd prefer to remain anonymous.

## Scope

Family Calendar is designed to run on a Raspberry Pi on a **trusted local network**. It is not hardened for direct public-internet exposure and has no multi-user authentication model.

### In scope

- Remote code execution, authentication bypass, or privilege escalation against a default installation.
- Vulnerabilities in the photo upload token system (`src/photo_upload/auth.py`) that allow unauthorized uploads or token forgery.
- Information disclosure of Google OAuth credentials, tokens (`*_token.json`), or session material.
- Vulnerabilities in third-party dependencies that materially affect Family Calendar (please also report upstream where possible).
- Cross-site scripting or request forgery against the web UI.

### Out of scope

- Issues that require an attacker already on the local network combined with physical access to the device.
- Missing security headers or cookie flags that have no practical exploit path given the local-network deployment model.
- Exposure of diagnostic information (e.g. `/pir/diagnostics`) — this is intentional for debugging hardware issues on a Pi.
- Denial-of-service via unauthenticated endpoints on the local network.
- Social engineering, physical attacks, or attacks requiring compromised Google accounts.
- Automated scanner output without a demonstrated exploit.

## Security Practices

This project uses:

- **Dependabot** for automatic dependency update PRs.
- **CodeQL** for static analysis on every push and pull request.
- **pip-audit** for dependency vulnerability scanning.
- **Bandit** for Python security linting.
- **Secret scanning** via pre-commit hooks and GitHub's native detection.

Weekly security scans run automatically, and the lockfile is refreshed whenever vulnerabilities are reported.

## Thank You

Thanks for helping keep Family Calendar and its users safe.

A few things to double-check before committing:
- The supported-version row (0.2.9) matches what you just tagged — update it when you cut future releases.
- The email fallback points to whatever address is on your GitHub profile; swap in a direct address if you'd rather.
- Response-time commitments are suggestions for a solo maintainer — tighten or loosen them to match what you can actually deliver.
