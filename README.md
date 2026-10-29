# Voicebox ARM64 CUDA container

Thin packaging of [Voicebox](https://github.com/jamiepine/voicebox) stable releases for Linux ARM64 CUDA. Upstream application source stays unchanged; this is not an application fork. Deployment is separate from image publication.

**Stable image published: `ghcr.io/michaelschmidle/voicebox-container:v0.5.0-r4`.** The [2026-09-22 promotion](https://github.com/MichaelSchmidle/voicebox-container/actions/runs/35751664330) set `v0.5.0-r4` and `latest` to OCI index digest `sha256:a6f581f66302261115b588527921ab3f21ce60e78ff57c2987f00dc7569b41f5` (packaging commit `dd798938c1738cefdfe0dbb3fbed640d4f5406a7`). Prefer the versioned tag or exact digest for traceability; `latest` is mutable.

The [exact-registry-digest evidence and independent publication approval](https://github.com/MichaelSchmidle/voicebox-container/issues/3) cover NVIDIA GB10 CUDA execution, health and Qwen CustomVoice synthesis for upstream v0.5.0. Publication accepts the disclosed inherited vulnerabilities, not a deployment or a vulnerability-free image. Other engines and production migrations remain untested. See [validation history and limits](docs/LOCAL_VALIDATION.md) and [security findings/disposition](docs/SECURITY_STATUS.md).

## Build and test locally

Requires an ARM64 Docker host, NVIDIA GPU/driver and NVIDIA Container Toolkit for GPU use. Python 3.12, torch/torchaudio 2.10.0 CUDA 13 and base digests are pinned. The build downloads upstream source and dependencies; model weights are downloaded at runtime, not distributed in the image.

```sh
docker build -t voicebox-container:local .
docker run --rm --gpus all --name voicebox-test \
  --memory=12g --memory-swap=12g --cpus=4 \
  -p 127.0.0.1:17495:17493 voicebox-container:local
```

This example uses disposable container storage. Open http://127.0.0.1:17495. Runtime user is 10001:10001; persistent application/model data belongs at `/app/data` with compatible ownership. Do not attach existing production storage merely to test a new release. Source licensing is retained at `/usr/share/licenses/voicebox/LICENSE`; dependencies and downloaded models have their own licenses.

## Release model

- Discover newer stable upstream releases into reviewable pin-update PRs, not arbitrary upstream main. Discovery does not infer new dependency locks or source checksums; those require review.
- Build reviewed candidates on native hosted ARM64 runners with SBOM, provenance and mandatory vulnerability evidence.
- Promote the exact tested registry digest to immutable `vVERSION-rREVISION` and mutable `latest` only after GPU/synthesis validation and independent security disposition approval. No deployment occurs.
- Inherited vulnerabilities are disclosed, not silently patched or hidden. Packaging fixes remain our responsibility. Image availability does not mean every deployment is safe.

Upstream discovery runs weekly on Tuesdays at 08:23 UTC and can also be started manually. It can open a reviewable pin-update PR; it never builds or publishes an image. Candidate builds and promotion remain manual workflows. [Release automation](docs/RELEASE_AUTOMATION.md) records settings, verification evidence, remaining integration limits and how to disable the schedule. Local tests do not establish hosted-runner capacity or registry publication.

Pinned inputs improve traceability; this build does **not** yet promise bit-for-bit reproducibility: apt repositories, frontend dependency resolution, source-package build dependencies and runtime model revisions remain moving inputs. The source archive checksum currently fails closed on unreviewed upstream changes.

Retire this packaging when upstream supplies an equivalent maintained ARM64 CUDA image.
