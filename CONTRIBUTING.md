# Contributing

Thank you for improving `delegate-to-deepseek-harness`. Keep changes focused, reproducible, and safe for a public Codex Skill repository.

## Before you start

- Read `SKILL.md` and `SECURITY.md` completely.
- Check `git status --short` and preserve unrelated work.
- Use this repository as the development source. Do not edit the installed Skill copy as the source of truth.
- Never commit Harness homes, credentials, settings, session logs, delegated task directories, or generated collaboration files.
- Open an issue first for changes that alter the security model, file-channel contract, supported Harness versions, or deployment-wide model behavior.

## Development setup

The runtime client requires Python 3.10+ and no third-party Python packages.

```sh
git clone https://github.com/papperrollinggery/delegate-to-deepseek-harness.git
cd delegate-to-deepseek-harness
python3 scripts/dsh_harness.py --help
```

Run the deterministic local checks:

```sh
python3 -c 'source=open("scripts/dsh_harness.py", encoding="utf-8").read(); compile(source, "scripts/dsh_harness.py", "exec"); print("syntax-ok")'
python3 -m unittest discover -s tests -v
python3 scripts/dsh_harness.py --help
python3 scripts/dsh_harness.py --base-url http://192.0.2.10:3080 probe
```

The non-loopback probe must exit non-zero.

## Change guidelines

### Skill instructions

- Keep frontmatter limited to `name` and `description`.
- Put every trigger and “when to use” signal in the description.
- Keep the body imperative, concise, and focused on operational knowledge Codex cannot safely infer.
- Preserve the no-subagent, current-Codex-task delegation loop.
- Keep `agents/openai.yaml` aligned with the actual Skill and ensure `default_prompt` includes `$delegate-to-deepseek-harness`.

### Python client

- Use only the Python standard library unless a dependency is essential and explicitly justified.
- Keep loopback enforcement fail-closed.
- Do not weaken redirect, proxy, secret-pattern, symlink, root-directory, same-cwd concurrency, active-session, or `minimal`-preset protections.
- Add a narrowly scoped regression test for behavior changes.
- Preserve model-written `RESULT.md`; use assistant text only when the file is absent.

### Documentation

- Keep `README.md` and `README.zh-CN.md` aligned on capabilities, limitations, installation, and safety.
- Update both use-case guides when a scenario or routing rule changes.
- Do not claim benchmark results, compatibility, media generation, isolation, or publication behavior without current evidence.
- Prefer direct links to official OpenAI, GitHub, and DeepSeek sources.

## Live Harness testing

Unit tests must not require credentials or a running Harness. When a behavior change needs an end-to-end test:

1. Use a disposable directory outside the repository.
2. Record the deployment default model before the test.
3. Create only new sessions owned by the test.
4. Record session ID, RPC ID, `turn/end` reason, `STATUS.json.status`, and relevant output contents.
5. Confirm that no pre-existing session was prompted, cancelled, renamed, or otherwise mutated.
6. Restore the previous default model using only a session created by the test.
7. Remove or securely discard test artifacts; never commit them.

Do not expose credentials or copy secret-bearing logs into an issue or pull request.

## Pull request checklist

- [ ] The change is limited to the stated problem.
- [ ] `git diff --check` passes.
- [ ] Syntax, unit tests, CLI help, and non-loopback rejection pass.
- [ ] Relevant English and Chinese documentation is synchronized.
- [ ] No secret, local absolute path, Harness state, session log, or generated task artifact is included.
- [ ] Live tests, if any, used only newly created sessions and document their bounded evidence.
- [ ] Compatibility and residual risk are stated honestly.

## Security reports

Do not open a public issue for a suspected vulnerability. Follow the private reporting process in `SECURITY.md`.
