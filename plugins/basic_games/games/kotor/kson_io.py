import json
import sys
import tempfile
from pathlib import Path

from py7z import ArchiveReader, write_7z
from py7z.entry import ArchiveEntryInput


_SEVEN_ZIP_SIGNATURE = b"7z\xbc\xaf'\x1c"


def load_kson(path: Path) -> dict:
    data = path.read_bytes()
    if not data.startswith(_SEVEN_ZIP_SIGNATURE):
        return _decode_json(data, path.name)
    dll_path = _seven_zip_dll()
    with ArchiveReader(path, dll_path=dll_path) as archive:
        files = [entry for entry in archive.entries() if not entry.is_directory]
        if len(files) != 1 or Path(files[0].path).suffix.casefold() != ".json":
            raise RuntimeError(f"{path.name} must contain exactly one JSON file")
        return _decode_json(archive.extract_entry(files[0].index), files[0].path)


def load_kson_bytes(data: bytes, source_name: str) -> dict:
    if not data.startswith(_SEVEN_ZIP_SIGNATURE):
        return _decode_json(data, source_name)
    with tempfile.TemporaryDirectory(prefix="kotorganizer_kson_read_") as temp_dir:
        path = Path(temp_dir) / Path(source_name).name
        path.write_bytes(data)
        return load_kson(path)


def write_kson(path: Path, payload: dict) -> Path:
    output_path = path.with_suffix(".kson")
    temp_output_path = output_path.with_name(f"{output_path.name}.tmp")
    with tempfile.TemporaryDirectory(prefix="kotorganizer_kson_write_") as temp_dir:
        json_path = Path(temp_dir) / f"{output_path.stem}.json"
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        entry = ArchiveEntryInput.from_path(json_path)
        try:
            write_7z(temp_output_path, [entry], _seven_zip_dll(), compression_level=9)
            temp_output_path.replace(output_path)
        finally:
            temp_output_path.unlink(missing_ok=True)
    return output_path


def _decode_json(data: bytes, source_name: str) -> dict:
    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{source_name} does not contain a JSON object")
    return payload


def _seven_zip_dll() -> Path:
    module_path = Path(__file__).resolve()
    for root in (Path(sys.executable).resolve().parent, *module_path.parents):
        dll_path = root / "dlls" / "7zip.dll"
        if dll_path.is_file():
            return dll_path
    raise RuntimeError("MO2's dlls\\7zip.dll was not found")
