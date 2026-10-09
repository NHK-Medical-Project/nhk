# NHK (`nhk`)

A **custom app** maintained by the company, installed in the NHK bench at
`/home/prasanth/bench-nhk`. It holds NHK's business logic: doctypes such as Item Service History, plus `doc_events`, `override_doctype_class`, `override_whitelisted_methods` and `scheduler_events` hooks.

This file is **local and untracked**. It is hidden through `.git/info/exclude`, not through the
committed `.gitignore`, so it never reaches `NHK-Medical-Project/nhk`. Do not commit it, and do not add it to
`.gitignore`.

## Read the bench context first

All shared context lives at the bench root, not in this repo. Read, in order:

1. `/home/prasanth/bench-nhk/CLAUDE.md` - bench-wide rules
2. `/home/prasanth/bench-nhk/CONTEXT.md` - domain glossary and system shape
3. `/home/prasanth/bench-nhk/docs/apps.md` - app inventory, install order, hook conflicts
4. `/home/prasanth/bench-nhk/docs/core-modifications.md` - before reading or editing `apps/frappe` or `apps/erpnext`

## Agent skills

### Issue tracker

Local Markdown at the **bench root**: `/home/prasanth/bench-nhk/.scratch/<feature-slug>/`, never in this
repo and never GitHub Issues. See `/home/prasanth/bench-nhk/docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles, written into each issue file's `Status:` line. See
`/home/prasanth/bench-nhk/docs/agents/triage-labels.md`.

### Domain docs

Single-context, shared across the whole bench: `/home/prasanth/bench-nhk/CONTEXT.md` and
`/home/prasanth/bench-nhk/docs/adr/`. Do not create a `CONTEXT.md` in this repo. See
`/home/prasanth/bench-nhk/docs/agents/domain.md`.

## Working in this repo

- **Source code here stays tracked and committed to `NHK-Medical-Project/nhk` (branch `360ithub_master`).** Only the AI workflow files are local.
- **Git commands run here**, inside `apps/nhk`: `git -C /home/prasanth/bench-nhk/apps/nhk status`, diffs, and `/code-review`.
- **Bench commands run from the bench root**: `cd /home/prasanth/bench-nhk && bench --site nhk.local ...`.
- The repo is a **shallow clone with one squashed commit**, so there is no useful history to
  review against. Review the working tree or a branch created from here on.
- Never run `git clean`, `git reset`, forced checkout, `bench migrate`, `git commit` or
  `git push` unless the user asks for that exact command.
- New behaviour belongs here rather than in ERPNext core. If it seems to need a core edit, that
  is a spec-level decision: write it up under the bench `.scratch/` first.

## Known issue in this app

**This app is barely wired in through hooks.** `hooks.py` contains only an empty
`scheduler_events = {"cron": {}}`; every `doc_events` and `override_doctype_class` line in it is
commented out. The app's logic reaches ERPNext because **ERPNext core was edited to import it
directly** (`erpnext/stock/doctype/item/item.py:70`).

`required_apps` is `[]`, yet that import runs at module load, so this app is a hard dependency
of the ERPNext fork: removing it breaks ERPNext, not just a feature.

Prefer adding real hooks here over deepening the core edits. That change is spec-first: write
it up under the bench `.scratch/` before touching either side.
