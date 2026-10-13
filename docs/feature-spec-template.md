# Feature spec: <title>

Slug: `<slug>` — branch `feat/<slug>`, worktree `.claude/worktrees/<slug>`.
Run with: `bash scripts/run_feature.sh <slug> <path-to-this-file> [budget_usd]`

## Goal

<One or two sentences: what changes and why.>

## Done when (testable)

- [ ] <Observable outcome, checkable by a command or a file's contents>
- [ ] <…>
- [ ] Tests listed under "How to verify" pass.

## Out of scope

- <Things not to touch or start, even if they look related>

## Constraints

- <Files/modules to reuse, interfaces that must not change, data limits
  (e.g. no holdout data), performance or dependency limits>
- Needs data/raw/market_data.sqlite? Say so in the spec and say whether it's
  read-only; the runner doesn't link it.

## How to verify

Exact commands, run from the worktree root:

```bash
bash scripts/run_tests.sh tests/test_<area>_*.py -q
<any CLI smoke check, e.g. python3 -m src.<module>.cli <cmd> ...>
```

## Workflow rules

- You are on branch `feat/<slug>` in `.claude/worktrees/<slug>`. Stay on it;
  don't create or switch branches.
- Commit in small steps on this branch, one logical change per commit.
- Edit files only with the Edit/Write tools, never with heredocs, `python -c`,
  `sed` or `awk`.
- Add the `docs/done.md` entry (the next `#N`, with a topic tag from its header)
  in this branch, as part of this PR.
- At the end, run the "How to verify" commands, then push with
  `git push -u origin feat/<slug>` and open a PR with `gh pr create`
  (no AI attribution in the commits or the PR body).
- Never merge, never force-push, never delete branches or worktrees.
- If a command is denied, stop retrying it. Don't rephrase it, wrap it
  (`sh -c`, `bash -c`, a script), use `git -C`, or call the binary by full
  path. Write `BLOCKED.md` at the worktree root with the exact command and
  why you needed it, leave it uncommitted, mention it in the PR body if a PR
  gets opened, and keep going on work that doesn't depend on it.
