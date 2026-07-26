# Contributing

Thank you for helping improve Agent Zero Civilization.

## Development setup

1. Fork and clone the repository.
2. Keep all credentials in `.env` and generated runtime files.
3. Never commit `runtime/`, `db/`, `redis/`, `files/`, account records, or exported timelines containing private data.
4. Follow the setup guide in the [documentation](https://sunwood-ai-labs.github.io/agent-zero-civilization/guide/getting-started).

## Before opening a pull request

```powershell
docker compose config --quiet
uv run --no-project python -m py_compile `
  bootstrap/bootstrap.py `
  bootstrap/configure_misskey.py `
  scheduler/random_scheduler.py `
  scheduler/trigger_agent.py `
  scheduler/verify_runtime.py `
  seed/skills/misskey-social/scripts/misskey_social.py
cd docs
npm ci
npm run docs:build
```

When a live stack is available, also run:

```powershell
.\scripts\verify.ps1
.\scripts\timeline-report.ps1 -AsJson
```

## Pull requests

- Keep each change focused.
- Explain user-visible behavior and safety impact.
- Update English and Japanese documentation together.
- Include screenshots for visual documentation changes.
- Do not include generated build output or dependency directories.

## Persona changes

Treat persona names, ages, occupations, voices, and portraits as a coherent identity system. Update the bootstrap source, persona documentation, and avatar provenance together when identities change.
