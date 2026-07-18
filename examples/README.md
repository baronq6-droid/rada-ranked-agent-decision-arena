# Live run example

`sample-run.json` is an unedited record of a live four-agent RADA run from
2026-07-18. Claude, Codex, Gemini Flash Lite, and Grok submitted anonymous
proposals and ranked them independently.

The most confident agent declared 95% confidence. Grok declared the lowest
confidence at 82%, but every juror ranked Grok's anonymous proposal first. Grok
won the Borda count 12-6-5-1, completed the task, passed the deterministic
verifier, and received a positive review from the runner-up.

The record contains the complete bids, votes, execution report, verifier result,
and model review. It was checked before publication for local paths, credentials,
API keys, email addresses, and session identifiers; none are present.

Canonical repository artifact (LF) SHA-256:
`53f6e8da0864010cead08809d845954d8fa427c5a619f041c014ee6b553f4519`

Verify it after a fresh clone:

```bash
sha256sum examples/sample-run.json
```

Private original (Windows, CRLF) SHA-256:
`5396b7c98c03e11d66e1629d04152e229e68a0aabcdb8ed57a52784799d1a091`.
The content is identical; the only difference is line endings, confirmed by
reconstructing CRLF from the repository's LF artifact. `.gitattributes` marks
the repository artifact as `-text` so Git does not rewrite its bytes at checkout.
