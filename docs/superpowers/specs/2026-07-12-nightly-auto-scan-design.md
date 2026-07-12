# Design: Nightly auto job-scan sourced from live portfolio data

**Date:** 2026-07-12
**Repo:** `autopilot-jobhunt` (fork `avinashgenaipeople/autopilot-jobhunt`)
**Owner:** Mohan Sagar Killamsetty

## Goal

Run the job scan automatically every night on GitHub Actions (not local cron), so it
fires even when the laptop is asleep. Each run rebuilds the candidate profile from the
**live `portfolio-data` repo** so the latest skills are always used, discovers remote
jobs suitable to that profile, scores them with an LLM, and pushes top matches to
Telegram. Failures also notify Telegram.

## Scope

- **In scope:** the profile adapter, matching config, local verification procedure,
  GitHub secrets + Actions workflow (nightly cron), and Telegram success/failure
  notification.
- **Out of scope:** changes to the scanner/scoring/drafter internals; the portfolio-data
  repo's own content model; using the hosted PDF resume (we generate a markdown resume
  instead).

## Repos & source of truth

| Repo | Role | Visibility |
|---|---|---|
| `avinashgenaipeople/autopilot-jobhunt` (this fork) | runs the scan + workflow | public |
| `mohansagark/portfolio-data` | source of truth for profile/skills (`data/*.json`) | public |

Both public → the Actions job checks out `portfolio-data` with no token, and the public
fork has unlimited free Actions minutes. The canonical profile data is the structured
`data/*.json` files (`profile.json`, `skills.json`, `experience.json`, `projects.json`,
`achievements.json`). The `claude-project-knowledge.md` doc is NOT on origin and is not
used. The candidate's actual resume is a PDF hosted on the portfolio site; we do not use
it — we generate a markdown resume from the JSON.

## Working directory

All commands (local and documented) run from the fork root:
`/Users/mohansagar/Documents/job-hunt/autopilot-jobhunt-forked`.
The local `portfolio-data` clone lives at `/Users/mohansagar/Documents/portfolio-data`
(i.e. `../../portfolio-data` relative to the fork root).

## Architecture & data flow

```
portfolio-data (GitHub, public)  ── source of truth: data/*.json
        │  local path (dev)  |  actions/checkout (CI)
        ▼
job_hunt/profile_sync.py   (NEW adapter, run as: python -m job_hunt.profile_sync)
        │   writes  → resume/YOUR_RESUME.md      (fresh markdown from JSON)
        │   patches → config.json candidate.{name,profile}
        ▼
autopilot scan
        │   TinyFish → discover remote jobs across 10 aggregator boards
        │   OpenRouter LLM → score each job vs fresh profile+resume (0–100)
        ▼
Telegram push (top N, score ≥ min)   +   commit state/last_scan.json back
(on failure)  →  Telegram: "❌ Run failed for {DATE}"  + Actions run link
```

## Component: `job_hunt/profile_sync.py` (new, ~60 lines)

- **Input:** `--src <path>` to a `portfolio-data` checkout (local path in dev; the
  checked-out `portfolio-data/` dir in CI). Optionally `--config` (default `config.json`)
  and `--resume` (default `resume/YOUR_RESUME.md`).
- **Reads:** `data/profile.json`, `data/skills.json`, `data/experience.json`,
  `data/projects.json`, `data/achievements.json`.
- **Writes** `resume/YOUR_RESUME.md`: markdown assembled from profile bio/headline,
  experience entries, featured projects, skills-by-category, achievements.
- **Patches** `config.json`: `candidate.name` (from `firstName`+`lastName`),
  `candidate.profile` (bio + headline + flattened skill names).
- **Fails loudly** (non-zero exit) if any required data file is missing or unparseable —
  so a scan never runs against a stale/empty profile. In CI this failure triggers the
  Telegram failure alert (below).
- Idempotent; safe to run at the start of every scan.

### Tests
- Unit test with a fixture `portfolio-data/data/*.json` → asserts the resume file and the
  patched `config.json` contain expected fields; asserts non-zero exit when a file is
  missing.

## Matching config (`config.actions.json`, committed — no secrets)

Coarse board search vs. fine LLM scoring:

- `search_keywords` (curated, stable — covers all three role families):
  `"AI engineer" OR LLM OR "machine learning" OR "frontend engineer" OR "frontend developer" OR "full stack" OR React OR "Next.js" OR "React Native" OR "software engineer"`
- `search_seniority`: `senior OR staff OR lead OR principal`
- India-remote is a **hard filter enforced in scoring**, not search:
  - `seeking`: "Fully remote, able to work from India (IST); global-remote OK; strong compensation"
  - `not_suitable`: "on-site/hybrid; remote roles geo-restricted to countries that exclude India"
  - No role-type exclusions (skills-match + pay is the bar).
- `min_score: 60`, `top_n: 8`.
- `llm_provider: openrouter`; key fields are placeholders overridden by env/secrets at runtime.
- `candidate.name` / `candidate.profile` are filled by `job_hunt/profile_sync.py` at run time.

## Local verification (Phase A — run from fork root)

1. `pip install -e .`
2. Create `.env` with: `TINYFISH_API_KEY`, `OPENROUTER_API_KEY`, `TELEGRAM_TOKEN`,
   `TELEGRAM_CHAT_ID`, `LLM_PROVIDER=openrouter`.
3. `cp config.actions.json config.json`
4. `python -m job_hunt.profile_sync --src ../../portfolio-data` → generates resume + profile.
5. `autopilot scan` → confirm a Telegram message arrives with scored jobs.
6. Only once green → proceed to GitHub.

Keys still to acquire before this phase: **OpenRouter** (openrouter.ai, free) and a
**Telegram bot + chat ID** (@BotFather; chat ID via @userinfobot or getUpdates).
TinyFish key already held.

## GitHub migration + Actions (Phase B)

**Secrets** (fork → Settings → Secrets and variables → Actions) — no resume secret; the
resume is generated:
`TINYFISH_API_KEY`, `OPENROUTER_API_KEY`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`.

**Enable Actions** on the fork (Actions tab → enable), since forks disable scheduled
workflows by default.

**Workflow `.github/workflows/nightly-scan.yml`:**
- Triggers: `schedule: cron "0 21 * * *"` (= 02:30 IST, UTC+5:30) + `workflow_dispatch`.
- `permissions: contents: write` (to commit state back).
- Steps:
  1. `actions/checkout` (this repo)
  2. `actions/checkout` with `repository: mohansagark/portfolio-data`, `path: portfolio-data` (public, no token)
  3. `actions/setup-python` (3.13)
  4. `pip install -e .`
  5. `cp config.actions.json config.json` (must precede sync — sync patches config.json in place)
  6. `python -m job_hunt.profile_sync --src portfolio-data`
  7. `autopilot scan` (env: the 4 secrets + `LLM_PROVIDER=openrouter`)
  8. `if: always()` — commit `state/last_scan.json` back with `[skip ci]`
  9. `if: failure()` — send Telegram `❌ Run failed for $(date -u +%F)` with a link to the
     Actions run (`$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID`),
     via `curl` to the Telegram Bot API using the Telegram secrets.

## Error handling & risks

- **Failure notification:** any failed step (sync or scan) → the `if: failure()` step
  posts `❌ Run failed for {DATE}` + run link to Telegram. This is independent of the
  scanner's own notifier, so it fires even if the scan crashed before scoring.
- **sync fails / data missing** → scan aborts (no stale-profile run); failure alert fires.
- **Telegram send failure** (success path) → logged, non-fatal (notifier returns False).
- **State commit** runs on `always()` so a failed scan still records partial state and
  keeps the schedule alive (avoids the 60-day auto-disable).
- **OpenRouter free quota (50 req/day):** broad keywords × 10 boards → more scoring calls.
  One nightly scan should fit; if "All LLM models failed" recurs, load **$10** on
  OpenRouter (the verified 1000/day threshold; $5 does not raise the free cap). Tuning
  knob, not a blocker. Can also narrow `search_keywords` or lower `top_n`.
- **India-remote leakage:** scoring reduces but won't perfectly exclude US-only "remote"
  roles; `not_suitable` handles most; tune `min_score` if noisy.
- **GitHub scheduler** typically fires 5–15 min late.

## Files created / changed

- NEW `job_hunt/profile_sync.py` (+ test)
- NEW `config.actions.json` (revise the earlier draft: add search config; profile filled at runtime)
- NEW `.github/workflows/nightly-scan.yml` (revise the earlier draft: add portfolio checkout + sync step + failure-notify step; drop the RESUME_MD secret/heredoc)
- NEW `docs/superpowers/specs/2026-07-12-nightly-auto-scan-design.md` (this file)
