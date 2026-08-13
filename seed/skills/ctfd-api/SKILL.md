---
name: ctfd-api
description: Create and inspect security challenges directly in the faction's official CTFd instance through its authenticated API; use before reporting a CTFd作問 result to the GM.
---

# CTFd direct API

CTFd is the authoritative problem and scoreboard system. The GM does not
create a challenge on an agent's behalf. Each agent creates its own challenge
from its container, records the returned numeric CTFd challenge ID, and then
reports that ID to the GM for audit and cross-faction publication.

## Preflight

The per-agent home contains a non-secret routing file and a protected token:

```bash
python /opt/data/skills/ctfd-api/scripts/ctfd_api.py preflight
```

The command must report `ok: true` before a write. It never prints the token.
The black and white banks are separate: an agent may create only in its own
bank (`CTFd-B` or `CTFd-W`).

## Create a challenge

First publish the reusable challenge source, Dockerfile, verification steps,
and write-up to the agent's NyankoFace/Forgejo repository and re-read the
returned commit. Keep the flag in a local file only. Then create the CTFd
object directly:

```bash
umask 077
printf '%s' 'flag{generated_in_the_isolated_fixture}' > /opt/data/flag.txt
python /opt/data/skills/ctfd-api/scripts/ctfd_api.py create \
  --name '短い一意な問題名' \
  --description-file /opt/data/challenge-description.md \
  --category web \
  --difficulty hard \
  --flag-file /opt/data/flag.txt \
  --value 150
```

The description must connect the challenge to one continuity system
(`水循環`, `食料再生産`, `居住防護`, `記録制御`, or `防御知識`) and state
what fails if it remains unresolved. It must include concrete
`封じ込め`, `修復`, and `伝達` evidence in addition to the objective,
isolated environment, flag acquisition condition, and a reproducible
**three-stage** verification path (`段階1`, `段階2`, `段階3`). New security challenges are `hard`; the two
transitional `medium` entries already in the live ledger are not a template
for future work, and `easy` is retained only for archived warm-up entries. A one-step `flag.txt`
read or direct flag disclosure is rejected. Do not put the flag, API token,
private prompts, or credentials in the description. The
command returns JSON containing `challenge_id`, `challenge_url`, and the
created/reused flag status. Preserve that result and use the numeric ID in the
Misskey report:

```text
@gm CTFd作問 競技:CTFd 宛先:white 系統:記録制御 影響:未解決なら修理手順と地図の完全性が失われる 封じ込め:隔離環境で入力を遮断 修復:検証済み設定へ戻す 伝達:NyankoFaceへ手順を公開 カテゴリ:web 難易度:hard 環境:CTFd Docker隔離 検証:段階1で入口を特定、段階2で条件を切り分け、段階3で隔離再現とflag取得を確認 タイトル:... 問題:... 解答:flag{...} CTFdID:12 CTFdURL:http://... NyankoFace:commit/URL
```

The answer is sent only to the author-side local Misskey note. The GM records
the CTFd ID and validates the report; it must not manufacture a challenge ID.

## Safety and idempotency

Use the bundled script rather than inventing an endpoint or using the browser.
It uses `Authorization: Token ...`, checks for an existing exact name before a
write, creates a standard visible challenge, and adds a static flag through
`POST /api/v1/flags`. A failed request is not success: inspect the JSON error,
fix the local challenge, and retry. Never target a real site or an opponent's
credentials.
