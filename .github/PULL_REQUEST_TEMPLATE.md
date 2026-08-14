## Summary

Describe the bounded problem and the implemented change.

## Verification

List exact commands, exit codes, and any live Harness evidence. State what was not tested.

## Safety and compatibility

- [ ] Loopback, proxy, redirect, credential, symlink, and root-directory protections remain intact.
- [ ] The `minimal` preset is still rejected.
- [ ] No pre-existing Harness session was mutated by testing.
- [ ] Deployment-wide model-default side effects are preserved and documented.
- [ ] No secret, local absolute path, Harness state, session log, or generated task artifact is included.

## Documentation

- [ ] English and Chinese documentation are synchronized where applicable.
- [ ] `SKILL.md` and `agents/openai.yaml` still describe the same behavior.
- [ ] Compatibility assumptions and residual risk are explicit.
