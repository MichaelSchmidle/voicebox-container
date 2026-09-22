# Initial ARM64 CUDA candidate validation

This is local image evidence, not a registry release or attestation. Packaging remains under development.

## Tested image

- Upstream: Voicebox v0.5.0, commit `2bcb98d1a8b6fe05e15fbc1559e3085669e4035d`.
- Local image ID: `sha256:a13c5a1ae63bee52dd76f2cb3b1efaf058a584a05cd5a06e4d74914ff715eaf0` (not an OCI registry index digest).
- Platform: linux/arm64; Python 3.12; torch/torchaudio 2.10.0+cu130.
- Hardware: NVIDIA GB10, driver 580.178.04.
- Test process: non-root UID 10001, isolated container writable layer, loopback-only HTTP port, 12 GiB memory/swap ceiling and 4 CPU limit. No production volumes mounted.

## Executed checks

- Native Docker build succeeded. The initial dependency install failed because the generated lock omitted the upstream custom wheel location for piper-phonemize; an explicit ARM64 CPython 3.12 wheel reference fixed resolution.
- A real CUDA 512x512 matrix multiplication completed and returned finite values.
- Initial application startup failed on missing `libatomic.so.1`; adding Debian `libatomic1` fixed startup.
- `/health` returned healthy and CUDA (NVIDIA GB10).
- Created a disposable preset profile using Qwen CustomVoice, Ryan, English.
- POST `/speak` with explicit engine and personality disabled returned a generation ID. Consumed `/generate/{id}/status` SSE through loading_model, generating and completed, then downloaded `/audio/{id}`.
- WAV decoded to 90,240 frames at 24,000 Hz: 3.76 seconds, 180,524 file bytes. Samples were finite and non-silent, peak absolute amplitude 0.571868896484375.
- Runtime logs confirmed Qwen CustomVoice 1.7B loaded; subsequent health reported approximately 3991 MiB allocated VRAM.
- Test container stopped after validation, releasing its model. Existing service containers remained running.

## Hardened r3 validation

- Image ID: `sha256:e895e03fab17c52635b80b48355a5ee3229750f62a496e9995ec7a20deca6c7f`.
- Debian 13 base, corrected virtualenv/filelock resolution, Python HTTP healthcheck instead of curl.
- Native build, Docker health status and real CUDA 512x512 matrix operation passed.
- Qwen CustomVoice completed; WAV: 61,440 frames, 24 kHz, 2.56 seconds, 122,924 file bytes; finite/non-silent, peak 0.683074951171875.
- Same isolated loopback-only, non-root, 12 GiB/4 CPU test pattern; inspected mounts were empty. Test container stopped afterward.
- PyTorch capability warning persists; successful tests do not remove that limitation.
- Scan inventory and inherited-risk assessment: [SECURITY_STATUS.md](SECURITY_STATUS.md).

## Limits and remaining gates

- PyTorch warns that reported compiled capability coverage ends at 12.0 while GB10 reports 12.1. The kernel and this synthesis passed; that does not establish every engine/kernel is compatible.
- Tested Qwen CustomVoice only; cloned Qwen, other engines, transcription, adapter end-to-end compatibility and subjective audio quality remain unverified.
- No production data, migrations or deployment tested.
- Initial scan and subsequent hardening are documented in SECURITY_STATUS.md. No independent review, hosted-runner build or registry publication has completed.
- Dependency versions/base image digests and upstream archive checksum are pinned, but frontend installation and source-package build dependencies still require reproducibility review. Do not claim bit-for-bit reproducibility.
- The automation draft and Dockerfile need integration review before release. Source checksum currently intentionally fails closed for any upstream commit other than the reviewed initial release.
