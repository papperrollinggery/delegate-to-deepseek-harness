# Use-case cookbook

[English](use-cases.md) · [简体中文](use-cases.zh-CN.md) · [Back to README](../README.md)

Use this cookbook when a larger project contains one workstream that is suitable for DeepSeek. Keep Codex as the controller in the current task; delegate only the bounded stage, then read and evaluate the result before continuing the project.

## Route before delegating

Answer five questions first:

1. **What is the smallest useful workstream?** Copy only, treatment review only, one code module, or one independent audit.
2. **Which directory contains all required inputs?** Prefer a dedicated workstream directory over the whole project root.
3. **Should DeepSeek edit project files?** If no, use `proposal-only`.
4. **Is the output text or media?** This Skill handles text and code. Use separate, authorized tools for media rendering, export, upload, or publication.
5. **Can the Harness deployment default model change?** New sessions persist the selected model as the RC.6 deployment default.

## 1. Copywriting inside a complex campaign

### Use it for

- Campaign territories, headlines, product copy, VO, supers, and CTA variants
- Tone adjustment against a provided brand guide
- Rewriting one approved message into channel-specific variants
- A second opinion on clarity, hierarchy, or abstraction

### Recommended route

| Decision | Default |
| --- | --- |
| Preset | `standard` |
| Model | `deepseek-v4-pro` for nuance; `deepseek-v4-flash` for low-risk iterations |
| Scope | `proposal-only` for options; dedicated `single-dir` when file edits are required |
| Directory | `/absolute/project/workstreams/copy` rather than the project root |

### Ask Codex

```text
Use $delegate-to-deepseek-harness for the copywriting workstream in
/absolute/project/workstreams/copy. Read brief.md and brand-voice.md. Produce
three campaign territories, each with one proposition, three headlines, a
30-word VO, and one CTA. Keep all supplied claims unchanged. Proposal only:
do not edit project files. Read the result and status back into this task.
```

### Acceptance check

- Every claim traces to the supplied brief.
- Variants are meaningfully different, not synonym swaps.
- Tone and length constraints are satisfied.
- `STATUS.json.status` is `done` and completion reason is `completed`.

## 2. Video-preproduction text work

### Good stages to delegate

- Treatment structure and story beats
- Script, VO, supers, lower-thirds, and title-card copy
- Shot-description clarity and continuity review
- Subtitle or transcript cleanup and segmentation
- Image/video generation-prompt preflight
- Identifying unsupported product claims or missing source material

### Do not describe these as completed video work

- Image or video rendering
- Editing a timeline or conforming media
- Color, sound mix, VFX, or final export
- Upload, client delivery, publication, or platform submission
- Rights clearance or claim verification without source evidence

### Recommended route

| Decision | Default |
| --- | --- |
| Preset | `standard` |
| Model | `deepseek-v4-pro` |
| Scope | `proposal-only` for review; dedicated `single-dir` for editable text artifacts |
| Directory | A treatment, script, transcript, or prompt-only folder |

### Ask Codex

```text
Use $delegate-to-deepseek-harness to handle the text-only video-preproduction
stage in /absolute/project/video-treatment. Review the 60-second story beats,
VO, supers, and shot descriptions. Return: (1) continuity issues, (2) a tighter
beat order, (3) revised copy, and (4) unsupported claims that need evidence.
Do not render, edit, export, upload, or publish media. Proposal only. Read back
RESULT.md, OPINION.md if present, and the final status.
```

### Acceptance check

- Story changes preserve supplied facts, timing, format, and mandatory beats.
- `VO`, `SUPER`, UI copy, and visual description remain distinct.
- Suggestions do not invent assets, product features, metrics, or approvals.
- The result is explicitly labeled as text preproduction, not finished media.

## 3. Fast rewrite or synthesis

Use `deepseek-v4-flash` for low-risk, reversible tasks where speed matters more than subtle reasoning: transcript summaries, copy shortening, structured extraction, or format normalization.

```text
Use $delegate-to-deepseek-harness with DeepSeek V4 Flash to turn the interview
notes in /absolute/project/research/interviews into a concise theme matrix.
Proposal only. Preserve quotations exactly, separate evidence from inference,
and read the result back. Changing the Harness deployment default to Flash is
acceptable for this run.
```

Do not choose Flash merely to reduce latency when the task contains high-stakes claims, complex cross-file dependencies, or nuanced brand language.

## 4. Focused code implementation

### Recommended route

| Decision | Default |
| --- | --- |
| Preset | `code` |
| Model | `deepseek-v4-pro` |
| Scope | `cross-file` only when multiple files are genuinely required |
| Directory | The smallest repository or package root containing the change and tests |

### Ask Codex

```text
Use $delegate-to-deepseek-harness to implement the bounded parser fix in
/absolute/project/packages/parser. Use the code preset and cross-file scope.
Read the local contribution rules first, change only parser behavior and its
regression tests, run the narrow test target, and report changed files and
verification. Do not commit, push, publish, or touch other packages.
```

### Acceptance check

- Diff stays inside the stated package and task.
- Regression coverage demonstrates the behavior change.
- Commands, exit codes, and untested areas are reported.
- Codex independently inspects the diff before presenting completion.

## 5. Independent review without edits

Use `proposal-only` when you want DeepSeek's analysis but Codex must retain full control of changes.

```text
Use $delegate-to-deepseek-harness to review /absolute/project for failure modes
in the current proposal. Do not modify project files. Put prioritized findings
with file references and suggested fixes in RESULT.md, optional strategic notes
in OPINION.md, and any required scope expansion in ASK.md. Read everything back
and evaluate it in this Codex task.
```

This is useful for architecture feedback, copy review, security-model critique, preflight checks, and alternative approaches. Treat the result as auxiliary evidence, not automatic approval.

## 6. Continue the same Harness conversation

After a completed delegation, continue the same session when the follow-up depends on its context:

```sh
python3 scripts/dsh_harness.py send SESSION_ID \
  --text-file /absolute/path/to/follow-up.txt \
  --no-wait
```

Use `wait SESSION_ID --rpc-id RPC_ID` later when the follow-up becomes a dependency. Use a new delegation when the working directory, authorization, task type, or write scope changes materially.

## Direct CLI pattern

Codex normally invokes the client for you. For manual use, keep long task text in a UTF-8 file outside the control filenames that `delegate` overwrites:

```sh
python3 scripts/dsh_harness.py delegate \
  --cwd /absolute/project/workstreams/copy \
  --preset standard \
  --model deepseek-v4-pro \
  --scope proposal-only \
  --title "Campaign copy review" \
  --text-file /absolute/project/briefs/delegate-copy.txt

python3 scripts/dsh_harness.py status \
  --cwd /absolute/project/workstreams/copy

python3 scripts/dsh_harness.py collect \
  --cwd /absolute/project/workstreams/copy --timeout 1

# Continue independent Codex work. When the result is required:
python3 scripts/dsh_harness.py collect \
  --cwd /absolute/project/workstreams/copy

python3 scripts/dsh_harness.py read-back \
  --cwd /absolute/project/workstreams/copy
```

`delegate` returns after acceptance by default. `--timeout` limits only a client-side collection wait and never cancels the Harness task; omit it only when the result is now a hard dependency and no independent Codex work remains.

Never place API keys, passwords, private keys, session cookies, or unrelated client data in the task file.
