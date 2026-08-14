---
name: delegate-to-deepseek-harness
description: "Use a locally running DeepSeek Harness for scoped, bidirectional collaboration over its loopback Web API and a cwd-pinned file channel. Delegate bounded copywriting, research synthesis, video-preproduction text, coding, review, or opinion work; read back results, suggestions, scope questions, and live status; continue an existing conversation; or control the local Harness service. Trigger when the user asks Codex to let DeepSeek or DeepSeek Harness handle part of a task, consult DeepSeek, collect a second opinion, process one workstream inside a complex project, or read back delegated work without creating a new Codex thread."
---

# Delegate to DeepSeek Harness

Use `scripts/dsh_harness.py` as the deterministic client. It speaks the Harness RPC API directly; do not automate the Web UI for ordinary session work.

## Safety rules

- Connect only to a literal loopback URL. The script rejects non-loopback hosts.
- Probe before acting. Start the service only when delegation requires it or the user asks to start it.
- Use `standard` by default. Never use `minimal`; the current RC.6 composition bypasses the file-write sandbox.
- Use `code` only for an explicitly coding-focused task. Use `cordis` only when the user explicitly asks to develop or alter Harness compositions.
- Choose `--cwd` from the actual task scope: a dedicated directory for self-contained work, the project root for cross-file work, and the project root plus `proposal-only` for advice that must not modify project files. Never select a home directory, credential directory, or unrelated client-data tree.
- Treat `workspace-write` as a write boundary only. It does not protect same-user readable secrets or restrict outbound network access.
- Treat `proposal-only` as an instructional expected-write guardrail. The actual Harness session write boundary remains the selected `cwd`; do not use `proposal-only` as read isolation or as protection for sensitive project files.
- Treat `--model` as a deployment-setting mutation. In RC.6, `session.selectModel` selects the new session model and also persists it as the deployment-wide `agent-default-model`; there is no separate pure session-only RPC. `create`, `run`, and `delegate` call it, defaulting to `deepseek-v4-pro`. An explicit `--model deepseek-v4-flash` therefore also changes the default observed by later blank sessions and the Web UI. If preserving the current deployment default is required, do not create a session with these commands; use an existing session with `send` or stop and ask before proceeding.
- Delegation never expands the user's authorization. Do not ask Harness to publish, deploy, message, pay, delete, expose credentials, or mutate external systems unless the user authorized that action.
- Do not pass secrets in task text. Never read or write Harness credentials through this Skill.
- Never auto-answer approval or question prompts. If a wait times out while the session remains active, tell the user to resolve the pending interaction in the Web UI.
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

3. Classify the task before creating a session:

   - `single-dir`: one self-contained directory.
   - `cross-file`: multiple files or directories under one project root.
   - `proposal-only`: read the project but only write collaboration control files.
   - Work outside the selected root, including `.env`, keys, system paths, or another project: delegate a proposal/diff only, or obtain explicit user authorization first.

4. Prefer `delegate` for a new task. It serializes calls for the selected directory, refuses reuse while a same-directory Harness session is running, archives the previous file channel, writes `SCOPE.md` and `TASK.md`, creates a cwd-pinned session, waits for a durable `turn/end`, writes `STATUS.json`, and preserves the model-written `RESULT.md` (falling back to final assistant text only when that file is missing):

   ```sh
   python3 scripts/dsh_harness.py delegate \
     --cwd /absolute/project/path \
     --preset standard \
     --model deepseek-v4-pro \
     --scope cross-file \
     --title "Focused task title" \
     --text "The bounded task, required output, constraints, and verification." \
     --timeout 900
   ```

   `--scope auto` selects `proposal-only` from explicit review-only language, otherwise `cross-file` when `--cwd` contains a project-root marker, and otherwise `single-dir`. Pass an explicit scope when the heuristic is ambiguous.

5. Read the file-channel response and live state:

   ```sh
   python3 scripts/dsh_harness.py read-back --cwd /absolute/project/path
   python3 scripts/dsh_harness.py status --cwd /absolute/project/path
   ```

6. Continue the same conversation when needed:

   ```sh
   python3 scripts/dsh_harness.py send SESSION_ID \
     --text "Follow-up instruction" \
     --timeout 900
   ```

7. Return the assistant text only after checking `completionReason`. A reason other than `completed` is not a successful completion.

For long or shell-sensitive prompts, write a scoped temporary text file with the normal file-editing workflow and pass `--text-file /path/to/task.txt`. Use low-level `run --no-wait` only when the user wants asynchronous delegation; preserve the returned `rpcId` for later `wait`.

## 委派循环协议

当用户交给你一个复杂目标时，作为总控留在当前 Codex 线程内持续循环，直到目标完成或出现明确阻塞。不要在每一步之后停下来等待用户。

1. 拆解目标，选择下一块可独立验收的工作；用 `delegate` 交给 DeepSeek，并明确指定 `cwd`、模型和 `scope`。
2. 等到对应 `turn/end` 后，用 `read-back` 读取 `RESULT.md`，并用 `status` 核对 `STATUS.json` 与实时运行状态。
3. 若存在 `ASK.md` 或 `OPINION.md`，在本线程内评估并回应；在用户已有授权与当前安全边界内，必要时调整范围后再次 `delegate`，不要仅因普通反问或意见停下来询问用户。若请求需要新增权限、高风险动作或超出用户授权，把它视为第 5 步的明确阻塞，不要擅自扩权。
4. 若 `STATUS.json.status` 为 `done` 且结果满足验收标准，结束循环并汇总给用户。
5. 仅当 `STATUS.json.status` 为 `blocked` 或 `error`，或同一子任务连续两次失败时，停止循环并向用户报告阻塞原因、已有证据和未完成范围。
6. 全程不得调用 `spawn_agent`，不得 fork 或创建新的 Codex 线程，不得向本循环创建的 Harness 会话之外的其它会话发送、取消或修改操作。

## File channel

- `SCOPE.md`: YAML scope with `write`, `read`, `forbidden`, and `taskType`.
- `TASK.md`: the delegated task plus the instruction to stop and write `ASK.md` instead of expanding scope.
- `RESULT.md`: the result read back by Codex. Preserve the model-written file; use final assistant text only as a missing-file fallback.
- `OPINION.md`: optional review comments or suggestions from DeepSeek.
- `ASK.md`: a question or request for scope expansion; do not auto-approve it.
- `STATUS.json`: durable status plus `sessionId`, completion reason, model, preset, scope, and update time.
- `.dsh-delegation-history/<run-id>/`: recoverable archive of the previous run's control files when `delegate` reuses a working directory. Keep it out of version control and treat it as sensitive task data, not as tamper-evident storage.

Do not prompt another Harness session for the selected `cwd` while a task is running. The per-directory lock coordinates this CLI's `delegate`, `run`, and `send` paths, not independent UI or third-party Harness clients.

`read-back` reads `RESULT.md`, `OPINION.md`, and `ASK.md`. `status` combines `STATUS.json` with the live `running` value from `session.list`.

## Session operations

```sh
# Concise session inventory
python3 scripts/dsh_harness.py list

# Create without prompting
python3 scripts/dsh_harness.py create --cwd /absolute/project/path --preset standard --model deepseek-v4-pro --title "Title"

# Low-level prompt path without SCOPE/TASK files
python3 scripts/dsh_harness.py run --cwd /absolute/project/path --preset standard --model deepseek-v4-pro --text "Task"

# Wait for one previously queued prompt
python3 scripts/dsh_harness.py wait SESSION_ID --rpc-id RPC_ID --timeout 900

# Read the last completed turn
python3 scripts/dsh_harness.py result SESSION_ID

# Cancel the active turn only when requested or necessary to stop the delegated work
python3 scripts/dsh_harness.py cancel SESSION_ID

# Open the local UI
python3 scripts/dsh_harness.py open-ui

# Stop only a server instance previously started by this script
python3 scripts/dsh_harness.py stop
```

Use `python3 scripts/dsh_harness.py --help` for all flags. The default endpoint is `http://127.0.0.1:3080`; override it with `--base-url` or `DEEPSEEK_HARNESS_URL`, still subject to the loopback-only check.
