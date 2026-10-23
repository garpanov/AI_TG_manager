# Security Policy

## Supported versions

AI Manager is currently an early-stage MVP. Only the latest revision on the default
branch receives security fixes.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or include credentials,
private Telegram content, personal data, or exploit details in public discussions.

Use GitHub's private vulnerability reporting feature for this repository when it is
enabled. If it is not available, contact the repository owner privately through the
contact method listed on their GitHub profile. Include the affected revision, impact,
reproduction steps, and any suggested mitigation. Share only the minimum data needed
to reproduce the issue.

You can expect an acknowledgement after the maintainer has reviewed the report. A
disclosure timeline will be coordinated based on severity and remediation complexity.

## Credential exposure

If a secret is exposed, revoke or rotate it immediately. Removing it from the latest
commit does not remove it from Git history, forks, caches, or logs. Clean the history
only after rotation, then verify it with a dedicated secret scanner.
