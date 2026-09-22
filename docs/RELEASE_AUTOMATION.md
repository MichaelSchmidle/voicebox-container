# Release automation

## Integration contract: Dockerfile and pins

The packaging owner must supply root `release.json` before running checks or enabling discovery. Its four fields are:

```json
{
  "repository": "jamiepine/voicebox",
  "version": "1.2.3",
  "commit": "0123456789abcdef0123456789abcdef01234567",
  "packaging_revision": 1
}
```

This is an illustrative schema, **not a real upstream pin**. Use a verified stable upstream version and resolved 40-character lowercase commit SHA. `version` is canonical `MAJOR.MINOR.PATCH` without `v`, prerelease or build suffix. Revision is a JSON integer in 1..999999, not a string or boolean. Do not put dependency/build pins in this file: those remain independently reviewed locks. Discovery changes only this file, resetting revision to 1 for a strictly newer upstream version. Dependency updates are deliberately not inferred; a discovery PR may need further human changes before it builds successfully.

The root Dockerfile must consume these build arguments:

| Argument | Source |
| --- | --- |
| `UPSTREAM_VERSION` | `release.json.version` |
| `UPSTREAM_COMMIT` | `release.json.commit` |
| `PACKAGING_REVISION` | `release.json.packaging_revision` |

It must fetch the exact upstream commit (not a moving version tag), verify/reconcile any additional build-lock pins, pin its base images and dependencies, retain licensing, and never bake model weights or user data into the image. Context is the repository root. Target is native `linux/arm64` on `ubuntu-24.04-arm`; there is no QEMU or self-hosted fallback. Hosted-runner availability and CUDA kernel/runtime compatibility are not established by these scripts. BuildKit supplies OCI SBOM and maximal build provenance; the candidate workflow adds signed GitHub/Sigstore provenance after mandatory scan evidence is retained (not a vulnerability-free claim).

## One-time repository settings (human actions, not performed by these files)

1. Review and merge the workflows, Dockerfile and real pins to protected `main`. Require independent code review, especially for `.github/`, Dockerfile, release scripts and pins. Protect workflow modification; actions on main are trusted publishing code.
2. Allow GitHub Actions to create pull requests. Discovery's job-scoped token has `contents: write`, `pull-requests: write` and `actions: write`; the last is solely for explicit checks dispatch. Organization policy may disable this option; do not work around it with a PAT.
3. Ensure GHCR package creation/access is enabled for this repository's `GITHUB_TOKEN`; set the resulting package public deliberately. No custom secrets, private runners or tunnels are required. If registry authorization or first-package creation checks fail, investigate configuration rather than treating authorization errors as “tag absent.”
4. Create the **`release` environment**, restrict it to protected main, require a trusted reviewer and enable **Prevent self-review**. The promotion script independently reads these protections and fails closed if required independent review is absent. The reviewer must inspect the digest, GPU evidence and security disposition before approving. GitHub calls this a deployment environment; this workflow only updates registry tags and GitHub audit metadata, never a running service.
5. All writers of candidate/version/latest tags must use this repository's shared `release-publish` concurrency group. Remove out-of-band publish credentials. OCI registries do not expose compare-and-swap tag writes: workflow serialization and exclusive write ownership are prerequisites, not a claim of transactional registry semantics.
6. Confirm repository settings/API token capabilities with a manual dry review, then execute the first real candidate and GPU validation.

## Discovery and PR checks

`discover.yml` is manually dispatchable on main. A weekly schedule is provided as **commented, disabled YAML**; only enable it after review. Discovery paginates upstream releases, filters drafts/prereleases/malformed versions, chooses the newest strictly greater semantic version, and resolves the release tag through the GitHub commits endpoint. Both annotated and lightweight tags resolve to the committed source SHA. Network reads retry transient failures a bounded number of times; authorization failures do not become empty results.

An update goes to `automation/upstream-vVERSION`; existing branches are never force-pushed and closed PRs are not automatically reopened. An existing mismatched pin requires human reconciliation. Before creating a PR, discovery runs the same tests, schema validation and workflow lint as normal checks.

**A `GITHUB_TOKEN`-created PR does not automatically run pull-request CI.** Discovery therefore explicitly dispatches `checks.yml` against the update branch using its `actions: write` permission. Workflow dispatch is one of GitHub's exceptions to recursive token-trigger suppression. Verify the dispatched `Packaging checks / checks` result on the current PR head before merging; a successful dispatch only requests a run and does not establish green CI. Standard pull requests and main pushes also run this read-only check job. Branch protection must require it. PR jobs receive no package publishing or OIDC permissions and never run on private hardware.

If a maintainer changes dependencies on the update branch, those human pushes normally trigger PR checks; verify the latest head again. Rerunning discovery never overwrites such follow-up changes when the release pin still matches.

## Candidate build (manual, never stable)

After the update PR is reviewed and merged, dispatch `candidate.yml` **on main**, supplying its exact 40-character `packaging_commit`. It must equal the workflow dispatch SHA and checked-out commit; arbitrary branches and pull-request refs are rejected. The invoking actor must currently have write/maintain/admin permission.

The workflow builds and pushes only:

```text
candidate-vVERSION-rREVISION-FULL_PACKAGING_COMMIT_SHA
```

It does **not** create `latest` or a stable version tag. It checks candidate-tag absence before publishing and never overwrites an existing candidate on retries. The Dockerfile consumes the reviewed upstream pins; OCI index annotations record both upstream and packaging commits. Native build output includes SBOM and provenance. Trivy scans the exact digest for HIGH/CRITICAL vulnerabilities, including unfixed issues; findings are disclosed, while scanner errors or missing evidence fail the build gate. A GitHub provenance attestation is signed only after valid scan evidence is uploaded. It attests provenance, not vulnerability absence. A rejected candidate may remain in GHCR, but without the required successful-workflow attestation it cannot be promoted by these scripts.

A retry after push/scan interruption does not overwrite the candidate. Inspect the existing run; normally increment `packaging_revision` in a reviewed commit and rebuild. There is no automatic deletion, cleanup or scan override. The candidate summary supplies the exact OCI index digest for external testing. Candidate artifacts include the scan report; Docker's build action also emits its build record. GitHub artifact retention is not indefinite—preserve needed evidence in the reviewed release issue.

## GPU validation and explicit promotion

GPU tests run separately on maintainer-controlled hardware, not from this repository's Actions workflows. No deployment or private connectivity is provided here. Pull and test the **exact OCI index digest**, not just the candidate tag. Validate architecture, application startup, CUDA execution and representative synthesis; do not expose private host identifiers, user data, model credentials or operational transcripts in public evidence.

Publish a public issue/PR or issue-comment in this repository containing:

- Exact `sha256:...` OCI index digest and full packaging commit SHA.
- GPU/driver/runtime characteristics sufficient for reproducibility (generic, sanitized).
- Commands/checks performed, CUDA execution evidence, synthesis outcome and known limitations.
- Human tester identity and independent review.

Then a trusted maintainer manually dispatches `promote.yml` on main with:

- `candidate_digest`: the exact tested SHA-256 digest.
- `packaging_commit`: the reviewed ancestor-of-main commit that built it.
- `gpu_evidence_url`: an HTTPS issue/PR or issue-comment URL in this repository.
- `gpu_validated`: explicitly **true**, attesting that this exact digest passed GPU startup and synthesis validation.
- `security_evidence_url`: a repository issue/PR/comment with the exact candidate digest and packaging SHA, scan inventory, dispositions, owners and re-evaluation triggers.
- `security_reviewed`: explicitly **true** after assessing the documented packaging and inherited risks for publication; this is not deployment acceptance. See [security policy and current assessment](SECURITY_STATUS.md).

The `release` environment requires another review. The script also reads this run's approval history and requires an approved review for that environment by a different user who currently has write/maintain/admin access; configuring reviewers or bypassing the gate is not sufficient. Disable administrative bypass in the environment settings as defense in depth. The script verifies both evidence records exist at the supplied URLs and contain the digest and packaging commit. Automation cannot determine whether a written human test claim is truthful; the attestation and independent approval are the trust boundary.

Promotion checks candidate tag/digest agreement, upstream/packaging annotations against the historical reviewed `release.json`, and GitHub signed provenance. `gh attestation verify` is constrained to the canonical repository, `.github/workflows/candidate.yml`, exact signer/source commit, main source ref, GitHub OIDC issuer and hosted runners. A random image, another workflow's image, mutable tag or unsigned failed scan cannot satisfy that policy.

The registry's immutable version tags establish a monotonic high-water mark, including partial previous promotions. An older version/revision is rejected even if latest has not yet advanced. `vVERSION-rREVISION` cannot be overwritten with another digest. Existing latest metadata must be valid. Candidate and promotion jobs share non-cancelling concurrency; tags are reread immediately before write. The script copies the **exact original manifest bytes**, first to `vVERSION-rREVISION`, then `latest`, and reads each tag back to verify the digest. No image rebuild or manifest synthesis occurs during promotion.

If the version write succeeds but latest fails, the workflow fails; rerunning with the same digest is safe and completes only missing tags. It will never roll latest backward after a newer version has been promoted. A fully successful retry is a no-op. Do not delete version tags: they are part of the durable rollback guard. There is no automated rollback path; recovery requires a new, reviewed higher packaging revision. Registry administrator/out-of-band mutation cannot be made safe by repository-local scripts.

`promotion-record.json` and `promotion-verification.json` are uploaded as the promotion audit artifact; the summary links evidence and records the digest. Preserve evidence before artifact expiry. Nothing here pulls an image onto a live host or changes a deployment.

## Local verification

```sh
python3 -m unittest discover -s tests -p 'test_release*.py' -v
python3 scripts/release.py validate
python3 scripts/release_lint.py
```

Tests are Python-standard-library-only and mock all GitHub/registry writes and external operations. `release_lint.py` downloads actionlint 1.7.7 for Linux AMD64/ARM64, verifies a pinned SHA-256 checksum, runs it, and removes the temporary executable. Shellcheck is used by actionlint when present. Workflow action references are pinned to commits; updates require review.

Local unit tests and workflow lint do **not** verify hosted-runner capacity, an actual ARM64 build, GHCR token/attestation interoperability or GPU synthesis. Those remain explicit integration gates. No schedule is enabled and no images are built/published/promoted merely by adding these files.
