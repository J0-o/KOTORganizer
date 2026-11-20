import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


SUBPROCESS_STARTUPINFO = None
SUBPROCESS_CREATIONFLAGS = 0
if os.name == "nt":
    SUBPROCESS_STARTUPINFO = subprocess.STARTUPINFO()
    SUBPROCESS_STARTUPINFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    SUBPROCESS_CREATIONFLAGS = subprocess.CREATE_NO_WINDOW



def file_hash(path: Path) -> str:
    exe = xxhsum_exe()
    if not exe:
        raise RuntimeError("xxhsum is required to calculate XXH3 hashes")
    result = subprocess.run(
        [exe, "-H3", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        startupinfo=SUBPROCESS_STARTUPINFO,
        creationflags=SUBPROCESS_CREATIONFLAGS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"xxhsum failed with exit code {result.returncode}: {result.stderr.strip()}")
    return parse_xxhsum_output(result.stdout)



def file_hashes(paths: list[Path]) -> dict[Path, str]:
    if not paths:
        return {}
    exe = xxhsum_exe()
    if not exe:
        raise RuntimeError("xxhsum is required to calculate XXH3 hashes")
    result = subprocess.run(
        [exe, "-H3", "--filelist", "-"],
        input="\n".join(str(path) for path in paths) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        startupinfo=SUBPROCESS_STARTUPINFO,
        creationflags=SUBPROCESS_CREATIONFLAGS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"xxhsum failed with exit code {result.returncode}: {result.stderr.strip()}")
    lines = result.stdout.splitlines()
    if len(lines) != len(paths):
        raise RuntimeError(f"xxhsum returned {len(lines)} hashes for {len(paths)} files")
    hashes: dict[Path, str] = {}
    for path, line in zip(paths, lines):
        value = parse_xxhsum_output(line)
        if len(value) != 16 or any(char not in "0123456789abcdef" for char in value):
            raise RuntimeError(f"xxhsum returned an invalid XXH3 hash for {path}: {line}")
        hashes[path] = value
    return hashes



def xxh3_bytes(data: bytes) -> str:
    exe = xxhsum_exe()
    if not exe:
        raise RuntimeError("xxhsum is required to calculate XXH3 hashes")
    result = subprocess.run(
        [exe, "-H3", "-"],
        input=data,
        capture_output=True,
        check=False,
        startupinfo=SUBPROCESS_STARTUPINFO,
        creationflags=SUBPROCESS_CREATIONFLAGS,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"xxhsum failed with exit code {result.returncode}: {stderr}")
    return parse_xxhsum_output(result.stdout.decode("utf-8", errors="replace"))



@lru_cache(maxsize=1)
def xxhsum_exe() -> str:
    for parent in (Path(__file__).resolve().parent, *Path(__file__).resolve().parents):
        for name in ("xxhsum.exe", "xxhsun.exe"):
            candidate = parent / name
            if candidate.exists():
                return str(candidate)
    exe = shutil.which("xxhsum") or shutil.which("xxhsum.exe") or shutil.which("xxhsun.exe")
    return exe or ""



def parse_xxhsum_output(output: str) -> str:
    first = output.strip().split()[0].strip("\\/")
    upper = first.upper()
    for prefix in ("XXH3_", "XXH128_", "XXH64_", "XXH32_"):
        if upper.startswith(prefix):
            return first[len(prefix):].lower()
    return first.lower()
