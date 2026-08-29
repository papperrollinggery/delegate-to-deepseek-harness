# DeepSeek Harness Auto-Start Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make operational DeepSeek delegation commands safely start and recover the loopback Harness service without repeated user authorization or an unsolicited browser window.

**Architecture:** Add one service-readiness boundary in `scripts/dsh_harness.py` that maps each operational command to a narrow startup directory, starts with normal Harness Home semantics when needed, and attaches a structured receipt. Keep `probe` read-only, preserve every existing safety invariant, and update the Skill/docs to make auto-start the default contract.

**Tech Stack:** Python 3 standard library, `unittest`, POSIX process/signals, DeepSeek Harness loopback RPC, shell install scripts, GitHub Actions/Releases.

---

### Task 1: Lock the lifecycle behavior with failing tests

**Files:**
- Modify: `tests/test_dsh_harness.py`

- [ ] Add focused tests asserting that a default start does not set `DSH_HOME`, an explicit Home does set it, and the child command ends in `--no-open`.
- [ ] Add CLI tests asserting operational commands call the readiness helper, `--no-auto-start` skips it, and `probe` never starts a service.
- [ ] Run `python3 -m unittest tests.test_dsh_harness.ServiceLifecycleTests tests.test_dsh_harness.CliTests -v` and confirm the new assertions fail for the missing behavior rather than a fixture error.

### Task 2: Implement minimal automatic readiness

**Files:**
- Modify: `scripts/dsh_harness.py`
- Test: `tests/test_dsh_harness.py`

- [ ] Add a startup-directory resolver that uses the client's private mode-0700 state directory, preventing delegated project `.env` files from becoming Harness launch environment.
- [ ] Change `start_server` to inherit normal `dsh` Home semantics, apply explicit `--dsh-home` only when supplied, and invoke `dsh web --port PORT --no-open`.
- [ ] Add readiness dispatch for `create`, `run`, `delegate`, `send`, `collect`, `status`, `wait`, `result`, `cancel`, and `open-ui`; attach its receipt to emitted JSON.
- [ ] Add `--no-auto-start` to those commands and keep `probe`, `list`, `read-back`, and `stop` outside readiness dispatch.
- [ ] Run the targeted lifecycle/CLI tests until they pass, then run `python3 -m unittest discover -s tests -v`.

### Task 3: Align the public contract and version

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `SECURITY.md`
- Modify: `CONTRIBUTING.md`
- Modify: `docs/use-cases.md`
- Modify: `docs/use-cases.zh-CN.md`
- Modify: `agents/openai.yaml`
- Modify: `llms.txt`
- Modify: `AGENTS.md`
- Modify: `VERSION`
- Test: `tests/test_repository.py`

- [ ] Replace the disposable-Home default with normal Harness Home inheritance and document the explicit override.
- [ ] State that invoking an operational delegation/continuation command authorizes safe loopback auto-start; keep credential, account, payment, scope, and approval boundaries human-gated.
- [ ] Document `--no-open`, `--no-auto-start`, service receipts, and `open-ui` behavior in English and Chinese.
- [ ] Bump the Skill version to `0.4.0` and update repository assertions if needed.
- [ ] Run repository and full unit tests.

### Task 4: Execute real cold-start and continuation verification

**Files:**
- Do not commit disposable smoke files or Harness state.

- [ ] Snapshot pre-existing session IDs and metadata without prompting or mutating them.
- [ ] Ensure no service owns port 3080, then run a new `delegate` without a preceding `start`; confirm the service receipt says `started` and no browser handoff occurs.
- [ ] Collect the new task to `done/completed`, read `RESULT.md`, and record session ID, RPC ID, model, reasoning effort, and turn-end evidence.
- [ ] Stop the owned service, invoke `status` or `collect` for the test task, and confirm continuation auto-start finds the persisted session.
- [ ] Restore the deployment-wide model default using only a session created by this smoke and confirm pre-existing session metadata is unchanged.

### Task 5: Review, install, and publish

**Files:**
- Review all changed runtime and documentation files.

- [ ] Run syntax, full tests, CLI help, shell syntax, loopback rejection, `git diff --check`, secret/local-path scans, and the official Skill validator.
- [ ] Run an independent cold review and locally verify every accepted finding.
- [ ] Install with `bash scripts/install-global.sh`, compare maintained runtime-file hashes, and verify executable bits.
- [ ] Open a fresh Codex task to verify Skill discovery and one project-external cold-start smoke.
- [ ] Commit the focused change, push the branch, merge it into `main`, and verify the exact-SHA CI result.
- [ ] Create and push `v0.4.0`, publish the GitHub release, download its archive, and compare source/install/archive runtime artifacts.
