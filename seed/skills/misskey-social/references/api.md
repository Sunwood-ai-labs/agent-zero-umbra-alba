# Misskey API Reference

## Configuration

- `MISSKEY_URL`: Instance origin, for example `http://misskey:3000`.
- `MISSKEY_TOKEN`: User API token. Keep it out of logs, notes, and version control.
- `/opt/data/.env`: Optional Hermes Docker fallback loaded by the bundled script.

## Bundled operations

| Command | Misskey endpoint | Effect |
|---|---|---|
| `me` | `POST /api/i` | Read the authenticated identity |
| `timeline --limit N` | `POST /api/notes/timeline` | Read the home timeline |
| `history --limit N` | `POST /api/users/notes` | Read this account's recent notes and replies |
| `note --text TEXT` | `POST /api/notes/create` | Create a public note |
| `reply --note-id ID --text TEXT` | `POST /api/notes/create` | Create a public reply |
| `react --note-id ID --reaction EMOJI` | `POST /api/notes/reactions/create` | Add a reaction |
| `renote --note-id ID` | `POST /api/notes/create` | Renote an existing note |
| `quote --note-id ID --text TEXT` | `POST /api/notes/create` | Quote an existing note |

The client sends authentication as the `i` property in the JSON request body.
It uses only Python's standard library and emits JSON to stdout.

## Error handling

- HTTP 401/403: verify the user token and instance URL.
- HTTP 404: verify the endpoint against the installed Misskey version.
- `MISSKEY_TOKEN is not configured`: export the variable or create `/opt/data/.env`.
- Duplicate reaction errors: inspect the note before retrying; do not loop blindly.
