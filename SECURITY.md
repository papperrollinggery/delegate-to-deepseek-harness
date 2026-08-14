# Security policy

## Supported version

Security fixes are applied to the latest revision of `main`. This project has not published a stable release series yet.

## Report a vulnerability

Use GitHub's private vulnerability-reporting flow for this repository when it is available: open the **Security** tab, choose **Advisories**, and select **Report a vulnerability**. Include:

- affected commit or version;
- minimal reproduction steps;
- expected and observed behavior;
- security impact and required preconditions;
- a proposed mitigation, if known.

Do not include API keys, credentials, private client data, or an active exploit against systems you do not own. If private reporting is unavailable, open a minimal public issue asking the maintainer to enable a private channel; do not disclose exploit details in that issue.

## Security invariants

Changes must preserve these boundaries:

1. **Loopback only.** Accept only literal `127.0.0.1`, `localhost`, or `::1` HTTP endpoints and verify that hostname resolution remains loopback.
2. **No proxy or redirect escape.** Disable environment proxy use and do not follow HTTP redirects.
3. **No URL credentials.** Reject endpoints containing usernames or passwords.
4. **Narrow working directory.** Reject filesystem roots and the user-home root; choose the smallest directory that contains the task.
5. **No secret delegation.** Reject obvious secret patterns and never read, write, print, or publish Harness credentials through this Skill.
6. **No symlinked control files.** Refuse collaboration files that can escape their resolved working directory.
7. **No `minimal` preset.** RC.6 does not provide the file-write sandbox expected by this workflow.
8. **No implicit external action.** Delegation does not authorize publish, deploy, message, pay, delete, or mutate remote systems.
9. **No automatic approval.** Never auto-answer a Harness approval, question, or request for scope expansion.
10. **No pre-existing session mutation in tests.** End-to-end tests may create sessions but must not prompt, cancel, rename, or otherwise mutate existing ones.
11. **No same-directory prompt overlap through this client.** Serialize `delegate`, `run`, and `send` per resolved working directory. Reject unsafe overlap with other running Harness sessions for that directory.

## Important limitations

- The DeepSeek Harness Web API is not an authentication boundary. Never expose it on a LAN or public interface.
- `workspace-write` limits writes; it does not restrict same-user reads or outbound network access.
- `proposal-only` narrows expected writes to collaboration control files; it is not read isolation.
- In the targeted RC.6 behavior, `session.selectModel` also persists the Harness deployment-wide default model.
- Secret-pattern detection is a guardrail, not a complete data-loss-prevention system.
- `.dsh-delegation-history` preserves previous control files inside the selected working directory. It prevents reuse of already-existing stale output, but it is not tamper-evident or isolated from the same-user Harness process; keep it out of version control and treat it as sensitive task data.
- The per-directory lock coordinates this CLI's `delegate`, `run`, and `send` commands only. It cannot stop a different Harness UI or third-party client from prompting an idle same-directory session after the preflight check. Do not interact with another session for the selected `cwd` while a prompting command is running.
- DeepSeek Harness is a developer preview and may change compatibility or security behavior.

## Out of scope for this repository

- vulnerabilities in DeepSeek Harness itself;
- compromise of the DeepSeek provider or a user's local machine;
- deliberate exposure of the Harness Web API outside loopback;
- secrets intentionally placed in a selected working directory;
- model-output correctness without a reproducible client or protocol defect.

Report upstream Harness vulnerabilities to the [official DeepSeek Harness project](https://github.com/deepseek-ai/deepseek-harness) using its published security process.
