# Security disposition: upstream v0.5.0, packaging r3

## Policy

This repository packages unmodified Voicebox source, not a security-patch fork. Fix compatible packaging defects; disclose inherited findings. Candidate publication is not a claim of vulnerability-free software or authorization to deploy it. Scan execution/report retention are mandatory. Findings alone do not reject faithful packaging; scanner errors do. Stable promotion additionally requires exact-registry-digest GPU evidence, an explicit security disposition and independent approval.

Do not silently force transformers 5.x against the upstream/Qwen constraints. Maintainers own packaging choices and disclosure; upstream projects own compatible library/application fixes; operators own deployment acceptance. Every new candidate requires fresh review, not a blanket inherited-risk exemption.

## Packaging changes and evidence

Local image `sha256:e895e03fab17c52635b80b48355a5ee3229750f62a496e9995ec7a20deca6c7f`:

- Moved the pinned Python 3.12 base from Debian 12 to Debian 13.
- Updated virtualenv 16.7.12 to 21.9.1, resolving CVE-2024-53899. This required filelock 3.32.7 instead of 4.0.1; the ARM64 dependency resolver succeeded. No upstream source patch or transformers override.
- Removed runtime curl, using Python's standard-library HTTP client for the healthcheck. Compilers, Git and Bun remain build-stage only. Retained FFmpeg, SoX and libsndfile for audio functionality; removing these would change application support.
- Trivy 0.74.0, fresh database: **46 distinct HIGH/CRITICAL advisory IDs across 210 package matches (209 HIGH, 1 CRITICAL)**, down from 94 IDs / 266 matches in r1. These are scanner matches, not confirmed exploit paths. Unfixed findings are included. See [machine-readable finding inventory](security-scan-r3.json).
- CUDA matrix operation, healthcheck and real Qwen CustomVoice synthesis passed after these changes. This is not evidence that all other engines work or that vulnerabilities are unreachable.

## Inherited findings and applicability

| Finding class | Observed surface and remaining uncertainty | Publication disposition / owner / trigger |
|---|---|---|
| transformers CVE-2026-4372; listed fix 5.3.0 | The installed implementation supports loading attention kernels from Hub configuration. Voicebox's `backend/backends/qwen_llm_backend.py` uses AutoModelForCausalLM.from_pretrained. Its model-size selector maps to three fixed Qwen repositories, not a supplied repository URL. Those loads do not pin model revisions, so repository/cache compromise remains relevant. No exploit was attempted. | Disclose as inherited model-loading risk; compatible fix owned by upstream. Reassess every candidate, upstream transformers/Qwen change, or change in model trust. Do not claim trust_remote_code=False is sufficient. |
| transformers CVE-2026-5241; listed fix 5.5.0 | Despite the advisory mentioning 5.2.0, installed 4.57.3 **does contain** LightGlueConfig forwarding serialized trust_remote_code to nested AutoConfig.from_pretrained. Therefore it is not dismissed as a version false positive. No LightGlue use was found in Voicebox backend source; this is limited source inspection, not proof of global unreachability. | Disclose; do not load arbitrary model configurations. Same upstream ownership and per-candidate/model-surface review trigger. |
| transformers CVE-2026-9856; listed fix 5.10.0 | Malicious chat-template names can affect save_pretrained. No save_pretrained invocation was found in Voicebox backend Python; dependency-internal calls and untested engines are not ruled out. | Disclose; upstream owns fix. Reassess when tokenizer/processor saving, model import or dependency behavior changes. |
| Debian multimedia/system libraries | FFmpeg/libav account for repeated matches against shared source advisories. Audio parsing is real functionality, so malicious media is a credible surface. The sole CRITICAL match is libxml2 CVE-2026-6653 (crafted XML use-after-free/DoS); its route through this application has not been established. The report lists no fixed versions for these Debian 13 matches. This does not establish absence of vendor fixes elsewhere. | Disclose without reachability claims. Debian/component upstream owns patches; packaging maintainer owns refreshing the base/packages. Reassess each candidate, newly available fixes or material exploit information. |

This assessment supports continued packaging and independent release review; it does not assert that every finding is acceptable in every deployment. No stable release has yet been approved.

## Deployment conditions to assess separately

Use only a trusted-user private service behind appropriate access controls; do not expose Voicebox unauthenticated to the internet. Model repositories, cached model files and input media must be trusted. Avoid host/Docker-socket mounts, credentials and unrelated writable storage; run non-root with explicit resource limits. These controls reduce exposure, not the existence of the defects. Multi-user/untrusted-media/model use needs a separate assessment. Containers sharing the host GPU/kernel are not a strong malicious-code sandbox.

## Promotion evidence

For the actual registry candidate, retain its unfiltered HIGH/CRITICAL scan, exact index digest, packaging commit, reviewed dispositions, owners and review triggers in a public sanitized issue/PR. Link that record through security_evidence_url and attest security_reviewed=true only after review. The independent release-environment reviewer assesses its content; automation checks record existence and digest/commit binding, not the truth of the risk judgment. Local image IDs and the present summary cannot substitute for registry-digest evidence.
