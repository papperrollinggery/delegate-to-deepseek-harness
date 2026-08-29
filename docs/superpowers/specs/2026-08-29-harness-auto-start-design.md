# DeepSeek Harness Auto-Start Design

## Problem and evidence

The client can start Harness, but the operating contract treats startup as an optional action after a failed `probe`. In a recent real delegation, `probe` returned connection refused, `start` launched a disposable Harness Home, and the delegated turn ended with `MISSING_CREDENTIAL`. The same launch also opened the Web UI because `dsh web` opens a browser unless `--no-open` is passed. The browser therefore suggested a manual continuation path even though the actual RPC turn had already failed for a different reason.

The normal Harness Home already owns the user's provider configuration and persisted sessions. The Skill must reuse Harness's normal Home semantics without reading, printing, or copying credentials.

## Chosen behavior

Calling an operational command is sufficient authorization to start the local loopback service. `create`, `run`, `delegate`, `send`, `collect`, `status`, `wait`, `result`, `cancel`, and `open-ui` automatically ensure that the service is ready before their existing logic runs. `probe`, `list`, `read-back`, and `stop` retain their current side-effect boundaries.

Automatic startup:

- launches the long-lived Web process from the client's private mode-0700 state directory, so Harness does not materialize a delegated project's `.env` into the service environment;
- inherits an existing `DSH_HOME` environment value;
- leaves `DSH_HOME` unset when the caller did not set it, allowing `dsh` to use its normal Home;
- uses an explicit `start --dsh-home` only when the caller deliberately asks for an alternate Home;
- always launches `dsh web` with `--no-open`;
- returns a structured service receipt alongside the command result;
- remains restricted to the already validated loopback URL.

An explicit `--no-auto-start` option remains available on operational commands for diagnostics and environments where lifecycle ownership belongs elsewhere.

## Alternatives considered

1. Documentation-only retry instructions. This preserves the current client but repeats the failure mode whenever an agent stops after `probe`, so it does not meet the requirement.
2. Default automatic startup inside operational commands. This is the selected option because the action that needs Harness also owns recovery, while `probe` stays read-only.
3. A permanent OS daemon. This would avoid cold starts but adds installation, boot persistence, lifecycle, and unauthenticated-listener risk outside the requested scope.

## UI and authorization boundary

Ordinary startup never opens a browser. `open-ui` first ensures the service is running, then explicitly opens the loopback URL and reports whether the platform accepted the request.

The client does not auto-answer Harness approval cards, questions, credential setup, account choices, payment prompts, or requests to expand scope. The Skill continues ordinary authorized work through the existing `send` and `collect` loop. A genuine human-attention state remains a reported boundary rather than being disguised as a startup failure.

## Failure handling

- Missing `dsh`, an unsafe startup directory, a non-loopback URL, an early server exit, or readiness timeout remains a hard error with the original diagnostic.
- If another process starts the same endpoint during recovery, the client re-probes and uses that ready service rather than treating the port race as a task failure.
- Owned-server state records lifecycle facts but never credentials or task text.
- The delegated session still receives the requested task `--cwd` through RPC; the neutral process directory changes only service boot context.
- Restarting for `collect` or `send` uses the normal persisted Harness Home, allowing the recorded session to be found again.

## Verification

1. Unit tests prove normal-Home inheritance, explicit-Home override, `--no-open`, auto-start coverage, opt-out behavior, and no auto-start for `probe`.
2. Existing syntax, CLI, repository, loopback, update, and installation tests remain green.
3. A real cold-start smoke uses only newly created sessions, records startup/session/RPC/completion receipts, confirms `RESULT.md` and `STATUS.json`, and verifies that pre-existing sessions were not prompted, renamed, cancelled, or otherwise mutated.
4. Source and installed runtime artifacts are hash-identical; a fresh Codex task discovers the updated Skill.
5. The exact pushed commit passes CI, and the GitHub release archive matches the source and global install.
