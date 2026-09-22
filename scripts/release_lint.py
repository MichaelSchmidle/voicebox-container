#!/usr/bin/env python3
"""Run checksum-pinned actionlint without system installation or Python deps."""
import hashlib
import io
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile
from urllib.request import urlopen

VERSION = "1.7.7"
CHECKSUMS = {
    "x86_64": ("amd64", "023070a287cd8cccd71515fedc843f1985bf96c436b7effaecce67290e7e0757"),
    "aarch64": ("arm64", "401942f9c24ed71e4fe71b76c7d638f66d8633575c4016efd2977ce7c28317d0"),
}


def main():
    if platform.system() != "Linux" or platform.machine() not in CHECKSUMS:
        raise RuntimeError("release_lint supports Linux AMD64/ARM64 only")
    arch, expected = CHECKSUMS[platform.machine()]
    url = f"https://github.com/rhysd/actionlint/releases/download/v{VERSION}/actionlint_{VERSION}_linux_{arch}.tar.gz"
    with urlopen(url, timeout=60) as response:
        archive = response.read()
    if hashlib.sha256(archive).hexdigest() != expected:
        raise RuntimeError("actionlint archive checksum mismatch")
    with tempfile.TemporaryDirectory(prefix=".actionlint-", dir=".github") as directory:
        binary = Path(directory).resolve() / "actionlint"
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            member = tar.getmember("actionlint")
            if not member.isfile():
                raise RuntimeError("unexpected actionlint archive member")
            binary.write_bytes(tar.extractfile(member).read())
        binary.chmod(0o700)
        subprocess.run([str(binary), "-color", *map(str, sorted(Path(".github/workflows").glob("*.yml")))], check=True)


if __name__ == "__main__":
    main()
