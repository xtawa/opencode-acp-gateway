# Repository instructions

- Use English conventional commit messages: `type: describe the change`.
- Verify ACP and OpenCode interfaces against official documentation/source before changing the bridge.
- Keep the gateway independent of MaiBot and AstrBot.
- Never commit runtime data, upstream credentials, API keys, bootstrap tokens, or chat contents.
- Test authentication, streaming, quota reservations, cancellation, subprocess cleanup, and session isolation when changing those paths.
