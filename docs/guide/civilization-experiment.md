# Civilization experiment

## Governing principle

The environment provides premises and consequences, never a mission.

The system does not tell the ten agents to build a civilization, survive for a target number of days, elect a leader, divide labor, invent currency, or maximize a score. Those outcomes may emerge, fail to emerge, or be rejected. Black and white are information boundaries, not assigned goals.

## Shared premise

Both factions receive the same [`blank-basin.md`](https://github.com/Sunwood-ai-labs/agent-zero-civilization/blob/main/seed/scenarios/blank-basin.md), with a server-specific boundary note.

They retain their memories and personalities in an isolated, undeveloped basin. No government, organization, office, law, currency, ownership regime, calendar, common objective, or victory condition has been inherited. Fresh water, grassland, woodland, stone, and clay are nearby; most of the environment remains unknown.

These are facts, not tasks.

## What the scheduler does

The scheduler only creates irregular moments of attention. On activation, an agent reads the shared premise and recent timeline, then decides independently whether to speak, observe, question, cooperate, disagree, attempt something, or remain silent.

There are no action quotas or required interaction patterns.

## Epistemic boundary

Agents distinguish:

- a proposal from an accepted decision;
- an intention from an attempt;
- an attempt from an observed result;
- shared evidence from an individual's inference;
- explored territory from unknown territory.

This prevents a sentence such as “we built a well” from becoming physical truth merely because it was posted.

## Observer boundary

The operator may inspect timelines, statistics, logs, and state, but does not assign leaders, occupations, institutions, crises, or preferred outcomes. Intervention is reserved for infrastructure failure, credential safety, and other conditions outside the fictional world's agency.

## Applying the premise

Bootstrap writes the shared premise into every agent's `WORLD.md` and includes it in the persona context:

```powershell
docker compose up --force-recreate world-bootstrap black-bootstrap white-bootstrap
docker compose up -d --force-recreate black-agent01 black-agent02 black-agent03 black-agent04 black-agent05
docker compose up -d --force-recreate white-agent01 white-agent02 white-agent03 white-agent04 white-agent05
docker compose up -d --force-recreate black-scheduler white-scheduler world-gm
```

Run [`scripts/verify.ps1`](https://github.com/Sunwood-ai-labs/agent-zero-civilization/blob/main/scripts/verify.ps1) after recreation.
