# Voicebox container packaging

## Scope
Package unmodified upstream Voicebox releases for Linux ARM64 CUDA. This is not an application fork. Keep application source external, pinned to an exact upstream commit. Preserve license notices. Do not distribute model weights or user data.

## Delivery and safety
- Work on isolated branches/worktrees, never implement directly on main.
- Read README and any design documents before changing workflows.
- Stable upstream releases produce candidates; candidate success alone does not authorize latest promotion.
- Promotion requires exact-digest GPU/synthesis validation and independent review. Deployment is separate.
- Never mount production data or stop existing services during tests.
- Never attach public pull-request jobs to a private self-hosted runner.
- No private hostnames, paths, addresses, secrets or operational transcripts in this public repository.
- Keep package publishing permissions job-scoped; PR checks receive read-only permissions.
- Do not interpolate event inputs into shell scripts. Validate identifiers, then pass through environment variables/argument arrays.

## Verification
Run all repository tests and workflow lint before PRs. Validate the real ARM64 build, GPU kernels, application startup and synthesis before claiming runtime compatibility. Preserve uncertainty and report blockers rather than marking unexercised gates passed.

## Maintenance
Use upstream version plus packaging revision for immutable release identity. Pin build inputs and record image digest, source SHA, SBOM and provenance. Never overwrite versioned artifacts on retries. Keep latest unchanged on failed or unvalidated candidates. Retire this packaging when an equivalent maintained upstream image is verified.
