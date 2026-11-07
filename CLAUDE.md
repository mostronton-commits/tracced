# tracced: notes for coding agents

- Interface changes follow [DESIGN-v2.md](DESIGN-v2.md), the look everyone gets since 0.8.0: its tokens, rules and
  motion. Where a design skill or a general habit disagrees, DESIGN-v2.md wins. If a change needs something it does not
  cover, settle it with the owner first, then add it to DESIGN-v2.md in the same commit.
  [DESIGN.md](DESIGN.md) describes the old look, which stays only behind the `design=old` cookie: do not change it.
- Before calling an interface change done, look at it at 1920, 1440, 1280, 768 and 390 px wide.
- Versions move slowly (owner, 04.10): a small release bumps the patch (0.7.1, 0.7.2), the minor only for a big step of
  the product, and 1.0 comes only with full copy-trading and EVM chains.
- Every release to `main` adds its entry to [docs/updates.md](docs/updates.md) in the same commit (owner, 04.10): the
  version, the date, two to seven bullets of a few words each about what a user sees, newest first.
