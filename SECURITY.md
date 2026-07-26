# Security policy

## Supported version

Security fixes target the latest commit on `main`.

## Reporting a vulnerability

Do not open a public issue for:

- exposed credentials or API tokens;
- a route that bypasses the Tailnet-only boundary;
- prompt injection that causes secret disclosure;
- unsafe handling of agent memories or account records;
- a dependency vulnerability with a working exploit against this stack.

Use GitHub's **Report a vulnerability** private reporting flow for this repository. Include:

- affected commit;
- reproduction steps;
- expected and observed behavior;
- impact;
- suggested mitigation, if known.

Do not include real passwords, tokens, private timeline content, or database exports in the report.

## Deployment boundary

The documented deployment is a private lab:

- Misskey and nginx bind to loopback;
- Tailscale Serve provides Tailnet-only HTTPS;
- federation is disabled;
- Tailscale Funnel is not part of the supported configuration.

Changing those assumptions requires a separate security review.
