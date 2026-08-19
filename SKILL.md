---
name: delegate-to-deepseek-harness
description: "Use a locally running DeepSeek Harness for scoped, asynchronous collaboration over its loopback Web API and a cwd-pinned file channel. Delegate a bounded writing, research, video-preproduction, coding, review, or opinion workstream while Codex continues independent work; monitor and collect long-running results without a fixed wall-clock limit; continue an existing conversation; or control the local Harness service. Trigger when the user asks Codex to let DeepSeek or DeepSeek Harness handle part of a task, consult DeepSeek, collect a second opinion, run work in parallel, or read back delegated work without creating a new Codex thread."
---

# Delegate to DeepSeek Harness

Use `scripts/dsh_harness.py` as the deterministic client. It speaks the Harness RPC API directly; do not automate the Web UI for ordinary session work.

At the start of a task, run `bash scripts/check-update.sh`. It reads GitHub's latest published release metadata at most once per day and fails silently when offline. If it prints an available update, tell the user and ask whether to update, but continue the current task. Never run `scripts/update-global.sh` without the user's explicit approval. Set `DSH_DISABLE_UPDATE_CHECK=1` to disable this check.

## Safety rules

- Connect to Harness only through a literal loopback URL. The RPC client rejects non-loopback hosts; the separate update checker may read only this repository's public latest-release metadata from GitHub.
- Probe before acting. Start the service only when delegation requires it or the user asks to start it.
- Use `standard` by default. Never use `minimal`; the current RC.6 composition bypasses the file-write sandbox.
- Use `code` only for an explicitly coding-focused task. Use `cordis` only when the user explicitly asks to develop or alter Harness compositions.
- Choose `--cwd` from the actual task scope: a dedicated directory for self-contained work, the project root for cross-file work, and the project root plus `proposal-only` for advice that must not modify project files. Never select a home directory, credential directory, or unrelated client-data tree.
- Treat `workspace-write` as a write boundary only. It does not protect same-user readable secrets or restrict outbound network access.
- Treat `proposal-only` as an instructional expected-write guardrail. The actual Harness session write boundary remains the selected `cwd`; do not use `proposal-only` as read isolation or as protection for sensitive project files.
- Treat `--model` as a deployment-setting mutation. In RC.6, `session.selectModel` selects the new session model and also persists it as the deployment-wide `agent-default-model`; there is no separate pure session-only RPC. `create`, `run`, and `delegate` call it, defaulting to `deepseek-v4-pro`. An explicit `--model deepseek-v4-flash` therefore also changes the default observed by later blank sessions and the Web UI. If preserving the current deployment default is required, do not create a session with these commands; use an existing session with `send` or stop and ask before proceeding.
- Delegation never expands the user's authorization. Do not ask Harness to publish, deploy, message, pay, delete, expose credentials, or mutate external systems unless the user authorized that action.
- Do not pass secrets in task text. Never read or write Harness credentials through this Skill.
- Never auto-answer approval or question prompts. A client wait deadline is not a task failure and never cancels the Harness turn; continue independent work and collect again later. Use the Web UI only when status or events show that human attention is actually needed.
- Never stop the owned Harness service while any session is still running. `stop` verifies live sessions and fails closed; an unresponsive owned process may still be stopped for recovery because its session state cannot be queried.
- Report the session id, preset, working directory, completion reason, and any unverified state.

## Route the workstream

- For copywriting, research synthesis, transcript structuring, and video-preproduction text, use `standard` with the narrowest dedicated workstream directory. Treat storylines, scripts, shot descriptions, on-screen copy, subtitle cleanup, and generation-prompt review as text work; do not claim this Skill renders, edits, or publishes video.
- For source-file implementation or repository-wide code review, use `code` and select the smallest project root that contains every required file.
- For an opinion, audit, or draft that must not alter project files, use `proposal-only`. Prefer this scope for first-pass copy alternatives and video treatment reviews.
- For fast, low-risk iterations, use `deepseek-v4-flash` only when the shared default-model mutation is acceptable. Keep `deepseek-v4-pro` as the default for nuanced writing, multi-file reasoning, and higher-cost error surfaces.
- Use `cordis` only when the user explicitly asks to develop or alter Harness compositions. Reject `minimal` in every workflow.

## Core workflow

1. Check the live service:

   ```sh
   python3 scripts/dsh_harness.py probe
   ```

2. If unavailable and starting it is in scope, use an explicit working directory. Add `--dsh-home` only when the intended Harness Home is already known:

   ```sh
   python3 scripts/dsh_harness.py start --cwd /absolute/project/path --open-ui
   ```

   Without `--dsh-home`, `start` uses a disposable Harness home under the OS temporary directory; it will not reuse provider configuration or sessions from the user's normal Harness home. `start`/`stop` require POSIX process and signal support. On unsupported platforms, start Harness manually and use the RPC commands only.

3. Classify the task before creating a session:

   - `single-dir`: one self-contained directory.
   - `cross-file`: multiple files or directories under one project root.
   - `proposal-only`: read the project but only write collaboration control files.
   - Work outside the selected root, including `.env`, keys, system paths, or another project: delegate a proposal/diff only, or obtain explicit user authorization first.

4. Prefer `delegate` for a new task. It serializes submission for the selected directory, refuses reuse while a same-directory Harness session is running, archives the previous file channel, writes `SCOPE.md` and `TASK.md`, creates a cwd-pinned session, submits the prompt, records `sessionId` and `rpcId` in `STATUS.json`, and returns immediately after acceptance:

   ```sh
   python3 scripts/dsh_harness.py delegate \
     --cwd /absolute/project/path \
     --preset standard \
     --model deepseek-v4-pro \
     --scope cross-file \
     --title "Focused task title" \
     --text "The bounded task, required output, constraints, and verification."
   ```

   `--scope auto` selects `proposal-only` from explicit review-only language, otherwise `cross-file` when `--cwd` contains a project-root marker, and otherwise `single-dir`. Pass an explicit scope when the heuristic is ambiguous.

5. While DeepSeek works, continue any independent Codex work in the current task. Do not repeatedly poll. At a natural checkpoint, inspect live state and perform a short collection check:

   ```sh
   python3 scripts/dsh_harness.py status --cwd /absolute/project/path
   python3 scripts/dsh_harness.py collect --cwd /absolute/project/path --timeout 1
   ```

   A `pending`/`running` result means the Harness task was not cancelled; continue local work and check again later. When the result becomes a hard dependency and no independent work remains, omit `--timeout` so `collect` waits for the matching `turn/end` with no wall-clock limit.

6. After `collect` reports `delegateStatus=done`, read the file-channel response and verify the durable and live state:

   ```sh
   python3 scripts/dsh_harness.py read-back --cwd /absolute/project/path
   python3 scripts/dsh_harness.py status --cwd /absolute/project/path
   ```

7. Continue the same conversation when needed. Add `--no-wait` when Codex has independent work to do:

   ```sh
   python3 scripts/dsh_harness.py send SESSION_ID \
     --text "Follow-up instruction" \
     --no-wait
   ```

8. Return the assistant text only after checking `completionReason`. A reason other than `completed` is not a successful completion.

For long or shell-sensitive prompts, write a scoped temporary text file with the normal file-editing workflow and pass `--text-file /path/to/task.txt`. Use `delegate --wait` only when its result is an immediate hard dependency and no independent Codex work can proceed. An explicit `--timeout SECONDS` limits only the client wait; it does not limit or cancel the Harness task.

## 委派循环协议

当用户交给你一个复杂目标时，作为总控留在当前 Codex 线程内持续循环，直到目标完成或出现明确阻塞。不要在每一步之后停下来等待用户。

1. 拆解目标，选择下一块可独立验收的工作；用默认异步的 `delegate` 交给 DeepSeek，并明确指定 `cwd`、模型和 `scope`，保存返回的 `sessionId` 与 `rpcId`。
2. 立即推进不依赖 DeepSeek 结果的其它工作，不在原地等待。到自然检查点再用 `status` 和短时 `collect --timeout 1` 检查；若仍在运行，继续本地工作。只有结果成为硬依赖且已经没有可并行工作时，才用不带 `--timeout` 的 `collect` 等待对应 `turn/end`。
3. `collect` 完成后，用 `read-back` 读取 `RESULT.md`，并用 `status` 核对 `STATUS.json` 与实时运行状态。
4. 若存在 `ASK.md` 或 `OPINION.md`，在本线程内评估并回应；在用户已有授权与当前安全边界内，必要时调整范围后再次 `delegate`，不要仅因普通反问或意见停下来询问用户。若请求需要新增权限、高风险动作或超出用户授权，把它视为第 6 步的明确阻塞，不要擅自扩权。
5. 若 `STATUS.json.status` 为 `done` 且结果满足验收标准，结束循环并汇总给用户。
6. 仅当 `STATUS.json.status` 为 `blocked`、`stalled`、`failed` 或 `error`，或同一子任务连续两次失败时，停止循环并向用户报告阻塞原因、已有证据和未完成范围。`running`、`pending` 或客户端等待截止都不是失败；`stalled` 只表示会话持续未运行且没有对应 `turn/end`，不会自动取消任务。
7. 全程不得调用 `spawn_agent`，不得 fork 或创建新的 Codex 线程，不得向本循环创建的 Harness 会话之外的其它会话发送、取消或修改操作。

## File channel

- `SCOPE.md`: YAML scope with `write`, `read`, `forbidden`, and `taskType`.
- `TASK.md`: the delegated task plus the instruction to stop and write `ASK.md` instead of expanding scope.
- `RESULT.md`: the result read back by Codex. Preserve the model-written file; use final assistant text only as a missing-file fallback.
- `OPINION.md`: optional review comments or suggestions from DeepSeek.
- `ASK.md`: a question or request for scope expansion; do not auto-approve it.
- `STATUS.json`: durable status plus `sessionId`, `rpcId`, pre-prompt `baselineSeq`, completion reason, model, preset, scope, and update time. The baseline lets `collect` recover even when early prompt events roll out of the Harness history window.
- `.dsh-delegation-history/<run-id>/`: recoverable archive of the previous run's control files when `delegate` reuses a working directory. Keep it out of version control and treat it as sensitive task data, not as tamper-evident storage.

Do not prompt another Harness session for the selected `cwd` while a task is running. The per-directory lock coordinates this CLI's `delegate`, `run`, and `send` paths, not independent UI or third-party Harness clients.

`read-back` reads `RESULT.md`, `OPINION.md`, and `ASK.md`. `status` combines `STATUS.json` with the live `running` value from `session.list`. `collect` waits for or briefly checks the recorded `sessionId`/`rpcId`, preserves a model-written result, and finalizes `STATUS.json`.

## Session operations

```sh
# Concise session inventory
python3 scripts/dsh_harness.py list

# Create without prompting
python3 scripts/dsh_harness.py create --cwd /absolute/project/path --preset standard --model deepseek-v4-pro --title "Title"

# Low-level prompt path without SCOPE/TASK files
python3 scripts/dsh_harness.py run --cwd /absolute/project/path --preset standard --model deepseek-v4-pro --text "Task"

# Collect the async file-channel task; no fixed wall-clock deadline
python3 scripts/dsh_harness.py collect --cwd /absolute/project/path

# Wait for one previously queued low-level prompt
python3 scripts/dsh_harness.py wait SESSION_ID --rpc-id RPC_ID

# For a fresh low-level run only, recover after its rpc event rolls out of history
python3 scripts/dsh_harness.py wait SESSION_ID --rpc-id RPC_ID --baseline-seq BASELINE_SEQ --baseline-fallback

# Read the last completed turn
python3 scripts/dsh_harness.py result SESSION_ID

# Cancel the active turn only when requested or necessary to stop the delegated work
python3 scripts/dsh_harness.py cancel SESSION_ID

# Open the local UI
python3 scripts/dsh_harness.py open-ui

# Stop only a server instance previously started by this script, and only when no session is running
python3 scripts/dsh_harness.py stop
```

Use `python3 scripts/dsh_harness.py --help` for all flags. The default endpoint is `http://127.0.0.1:3080`; override it with `--base-url` or `DEEPSEEK_HARNESS_URL`, still subject to the loopback-only check.

Use `--baseline-fallback` only when no earlier turn can finish after the supplied baseline, such as a fresh session created by `run --no-wait`. Do not use it for a prompt queued behind an existing running turn; ordinary RPC matching remains fail-closed there.
