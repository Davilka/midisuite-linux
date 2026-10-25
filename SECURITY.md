# Security policy

## Supported versions

Security fixes are applied to the latest release and to the `main` branch.
Older releases may not receive fixes.

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.  Use GitHub's
private vulnerability reporting:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Describe the issue, the affected version and the steps to reproduce it.

If private reporting is unavailable, open a minimal issue asking for a private
contact channel and do not include exploit details.

## Scope

The application talks to a local MIDI device and checks GitHub Releases for
updates.  Relevant reports include:

* unsafe archive or file handling;
* credential or token leakage;
* unintended network requests;
* local privilege escalation through the launcher or update check.

The project never installs updates automatically: the update dialog only opens
the release page.

## Secrets

No tokens, credentials or personal hardware identifiers should be committed.
Local device backups live in the ignored `backups/` directory and must not be
published.
