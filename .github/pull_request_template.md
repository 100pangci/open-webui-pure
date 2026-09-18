<!--
Target `main`. There is no `dev` branch and no CLA bot in this fork.
-->

# Pull Request

Thanks for improving Open WebUI Pure! Keep in mind what this fork is:
an aggressively subtractive, OpenAI-compatible, SQLite-first chat core.
Read `HANDOFF.md` (product boundary) before proposing anything that adds a
feature, dependency or background process.

## Summary

What changes, and why does the fork still need it?

## Scope check

- [ ] This PR targets `main`.
- [ ] The change does not re-add a removed feature or dependency (see "Removed" in `README.md`).
- [ ] For upstream fixes: I linked the upstream issue/PR and adapted the fix to the trimmed codebase.
- [ ] No machine-specific paths, proxies or hostnames are hardcoded.

## Testing

```bash
PYTHONPATH=backend pytest backend/open_webui/test -q
npm ci
npm run test:frontend
npm run build
```

- [ ] Backend tests pass.
- [ ] Frontend tests and build pass.
- [ ] I updated `HANDOFF.md` if the product boundary, footprint or optional dependencies changed.

## Notes for reviewers

Anything that needs context, trade-offs you considered, or behaviour that
intentionally differs from upstream.
