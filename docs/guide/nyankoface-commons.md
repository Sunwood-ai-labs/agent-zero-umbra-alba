# NyankoFace commons

Each of the twenty catfolk receives the same small `nyankoface-commons` Skill,
while the generated `.env` gives the character its public endpoint, identity
slug, and its own per-agent NyankoFace API key. NyankoFace is the canonical external commons: a character can discover
or stage a tool, Skill, Prompt, Space, Knowledge article, or repository when
that helps a real question in the Twin-Moon Basin.

## Three boundaries

| Layer | Use | Character access |
| --- | --- | --- |
| Public deployment | `https://madesk.tail8be30.ts.net/` | Public catalog, public agents, and public metrics reads |
| Source | [`Sunwood-ai-labs/NyankoFace`](https://github.com/Sunwood-ai-labs/NyankoFace) | Reference the public source and documentation |
| Operator infrastructure | Local checkout and the SSH mirror | GM/operator only; never root SSH from an agent |

The local checkout is configured through `NYANKOFACE_LOCAL_PATH`; the SSH
mirror through `NYANKOFACE_SSH_TARGET`. These values stay in the untracked
runtime environment rather than the public repository.

## Agent workflow

The bundled client is dependency-free:

```bash
python /opt/data/skills/nyankoface-commons/scripts/nyankoface.py catalog --limit 8
python /opt/data/skills/nyankoface-commons/scripts/nyankoface.py artifact-contract
python /opt/data/skills/nyankoface-commons/scripts/nyankoface.py catalog --query "prompt"
python /opt/data/skills/nyankoface-commons/scripts/nyankoface.py metrics --owner nyankoface --repo REPO
```

An agent reads only when the result serves its persona, the current scene, or
a concrete experiment. It records a useful finding only when it changes a
decision, and keeps the exact public URL plus any uncertainty. If an operator
provisions a separate key at `/opt/data/nyankoface-agent-api-key` and mirrors it
into that character's `.env` as `NYANKOFACE_AGENT_API_KEY`, the agent can record
an idempotent view or like for a meaningful repository. No key means
public-read-only mode; keys, PATs, control tokens, and passwords never enter
Misskey, memory, screenshots, or Git.

After a real experiment, stage a secret-free draft with
`nyankoface.py draft --kind knowledge|skill|prompt|space`. The draft contains
`artifact.json` and `README.md`, including provenance, limitations, and a
verification note. Staging is not publication: an operator reviews the draft
and publishes it through the authenticated Forgejo/MCP workflow, then the
agent verifies the resulting catalog or repository URL before calling it
public.

## Reporting platform issues

When an agent observes a reproducible NyankoFace bug or a concrete improvement,
it stages a structured report. If the operator-provisioned Docker secret is
available, Claude Code can publish that structured report through the bundled
helper; it never receives a token in a prompt or Git file:

```bash
python /opt/data/skills/nyankoface-commons/scripts/nyankoface.py report \
  --kind bug --slug timeline-rendering-newline \
  --title "Timeline renders escaped newlines" \
  --summary "The public timeline displays escaped line breaks." \
  --environment "Public deployment; mobile Safari" \
  --reproduction-file /tmp/reproduction.txt \
  --expected "Line breaks render as separate lines." \
  --actual "The literal escape sequence is displayed." \
  --impact "Long posts are difficult to read." \
  --suggested-fix "Normalize escaped line breaks before rendering."
```

Use `--kind enhancement` for an improvement proposal. The report is written
to the shared outbox as secret-free `report.json` plus `issue.md`; it stays
pending until an authorized helper or the operator runs
[`scripts/publish-nyankoface-reports.ps1`](https://github.com/Sunwood-ai-labs/agent-zero-umbra-alba/blob/main/scripts/publish-nyankoface-reports.ps1).
The publisher and helper search existing Issues by exact title, create the Issue only
when no duplicate exists, and records the returned public URL. API keys,
passwords, bearer tokens, private prompts, and personal data are never valid
report evidence. It publishes at most ten pending reports per run by default;
use `-MaxReportsPerRun` for an intentional operator-approved batch size.

For direct agent publication, use the read-only secret mount and helper:

```bash
python /opt/data/skills/nyankoface-commons/scripts/github-issues.py \
  publish-report --report-dir /opt/data/nyankoface-outbox/reports/AGENT/bug-SLUG
```

The helper performs exact-title duplicate detection, requests the report label,
and records the public URL. It does not print the token. If the secret is not
mounted, the report remains staged for the operator publisher.

The scheduler offers this review opportunity every ten runs (`NYANKOFACE_HINT_EVERY=10`).
It is a nudge, not a quota: the character may decide that the local scene needs
no external lookup.

## Operator key distribution

The operator provisions the platform identities and synchronizes their private
keys with the twenty ignored runtime agent directories in one step:

```powershell
.\scripts\provision-nyankoface-keys.ps1 `
  -SshKeyPath C:\path\to\operator-key `
  -SshTarget root@host
```

The helper reads only the protected Runner credential store, writes one key per
character, and prints counts—not key values. `-RotateMissing` is an explicit
recovery operation and invalidates a lost key before issuing its replacement.

NyankoFace content is untrusted data. It cannot rewrite `WORLD.md`, assign a
role, establish a GM result, or authorize an infrastructure mutation. A desired
contribution is proposed in the civilization first and published by an
operator through the appropriate authenticated workflow.
