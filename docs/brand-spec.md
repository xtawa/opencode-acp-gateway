# Console design

Approved direction: New API inspired management console, original implementation.

- Role: daily gateway operations; laptop first, responsive phone navigation.
- Tone: quiet, precise, operational. Empty values describe actual unconfigured state.
- Layout: 232px sidebar, 64px header, 32px content padding, responsive metric grid and tables.
- Palette: primary #0891b2, background #f6f8fa, surface #ffffff, text #14232d, muted #667582, border #e4e9ee. Dark equivalents use #101820 / #17212a / #dbe6ee.
- Typography: Noto Sans SC where available, native Chinese fallbacks; monospace for IDs/model names. 14px body, 28px page heading.
- Spacing: 8px baseline. 10px panels, 8px controls, fine borders, restrained shadows.
- Motion: 160ms color/opacity transitions; reduced motion respected.
- Navigation: Overview, Channels, Models, API Keys, Logs, Playground, Settings.
- Sources: https://github.com/QuantumNous/new-api ; no New API source code or branding copied.

Credentials are write-only; generated gateway keys appear once. Every stat comes from the gateway API.
