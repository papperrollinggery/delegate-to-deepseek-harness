# Project handoff

This repository is the canonical development source for the public Codex Skill `delegate-to-deepseek-harness`.

## Start here

1. Read this file and `SKILL.md` completely before changing code.
2. Run `git status --short` and preserve unrelated user changes.
3. Develop and commit in this repository. Do not treat the installed Skill directory as the source of truth.
4. Do not commit Harness homes, credentials, settings, session logs, delegated task directories, or test artifacts.

Public repository: `https://github.com/papperrollinggery/delegate-to-deepseek-harness`

## Repository layout

- `SKILL.md`: triggering metadata, operating workflow, safety rules, and delegation-loop contract.
- `agents/openai.yaml`: UI-facing Skill metadata.
- `scripts/dsh_harness.py`: Python 3 standard-library client for the local Harness RPC API.
- `VERSION`: installed and published Skill version.
- `scripts/check-update.sh`, `scripts/install-global.sh`, `scripts/update-global.sh`: approval-aware update detection and global installation lifecycle.

The installed runtime copy normally lives at:

```text
${CODEX_HOME:-$HOME/.codex}/skills/delegate-to-deepseek-harness
```

Keep this repository as the development source and the Codex Skills directory as a tested installation copy. Do not replace the installation with a symlink unless Skill discovery through that symlink has been verified in a fresh Codex task.

## Current baseline

- Initial public commit: `8ce4064`.
- Default endpoint: `http://127.0.0.1:3080`.
- Supported models: `deepseek-v4-pro` and `deepseek-v4-flash` through provider `deepseek-official`.
- `minimal` preset is deliberately rejected.
- `delegate` creates `SCOPE.md`, `TASK.md`, `STATUS.json`, and a cwd-pinned Harness session, then returns after prompt acceptance by default.
- `collect` checks or waits for the recorded `sessionId`/`rpcId`, preserves `RESULT.md`, and finalizes durable status. There is no default wall-clock wait limit.
- A model-written `RESULT.md` is preserved. Final assistant text is used only when `RESULT.md` is missing.
- `read-back` reads `RESULT.md`, `OPINION.md`, and `ASK.md`; `status` combines `STATUS.json` with live session state.
- `REPLY.md` is a proposed future append-only response channel; it is not implemented yet.

## Safety invariants

- Accept only loopback Harness RPC endpoints: `127.0.0.1`, `localhost`, or `::1`. The separate daily update check may read only this repository's public latest-release metadata and must never send task content.
- Never expose the Harness Web API on a non-loopback interface. It has no authentication boundary.
- Treat `workspace-write` as a write boundary only. It does not restrict reads or outbound network access.
- Never pass, read, print, persist, or publish model credentials or task secrets.
- Never use the `minimal` preset. Its RC.6 composition does not provide the expected file-write sandbox.
- `session.selectModel` also persists the deployment-wide default model. Every `create`, `run`, or `delegate` call therefore has a shared settings side effect. Record the default before model-switching tests and restore it afterward using only a session created by that test.
- E2E tests may create new Harness sessions, but must not prompt, cancel, rename, or otherwise mutate pre-existing sessions.
- The delegation loop stays in the current Codex thread: do not call `spawn_agent`, fork a thread, or invoke `codex exec` on DeepSeek's behalf.

## Development workflow

Make the smallest necessary change, then validate from this repository:

```sh
python3 -c 'source=open("scripts/dsh_harness.py", encoding="utf-8").read(); compile(source, "scripts/dsh_harness.py", "exec"); print("syntax-ok")'
python3 scripts/dsh_harness.py --help
python3 scripts/dsh_harness.py probe
python3 scripts/dsh_harness.py list
```

For loopback enforcement, verify that a non-loopback URL exits non-zero:

```sh
python3 scripts/dsh_harness.py --base-url http://192.0.2.10:3080 probe
```

When behavior changes, add a narrowly scoped real delegate smoke test under a disposable directory such as `~/work/delegated/<test-name>`. Record:

- session id and rpc id;
- `turn/end` reason;
- `STATUS.json.status`;
- relevant output-file contents;
- model default before, during, and after the test;
- confirmation that no pre-existing session was mutated.

Do not commit the disposable directory.

## Install or refresh the runtime copy

After the Work repository version passes validation, install only the maintained runtime artifacts:

```sh
bash scripts/install-global.sh
```

Then compare hashes and confirm the script remains executable. Open a fresh Codex task when Skill discovery or updated instructions must be verified.

## Release and publishing

- The GitHub repository is public. Scan staged changes for secrets, local absolute paths, settings, logs, and test artifacts before every push.
- Do not commit or push unless the user explicitly requests it.
- Keep `main` releasable: syntax check, CLI help, loopback rejection, and relevant targeted tests must pass before publishing.
- The repository is licensed under the MIT License. Preserve `LICENSE` and keep public documentation aligned.
