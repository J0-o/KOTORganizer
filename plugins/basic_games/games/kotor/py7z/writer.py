"""Minimal 7-Zip archive writer backed by MO2's 7zip.dll."""

from __future__ import annotations

import ctypes
from pathlib import Path

from ._callbacks import UpdateCallback
from ._com import HRESULT_T, PVOID, check_hr
from ._dll import create_out_archive
from ._guids import CLSID_7z, IID_ISetProperties
from ._propvariant import PROPVARIANT, VT_UI4
from ._streams import FileOutStream
from .entry import ArchiveEntryInput


_UPDATE_ITEMS_FUNC = ctypes.WINFUNCTYPE(HRESULT_T, PVOID, PVOID, ctypes.c_uint32, PVOID)
_SET_PROPERTIES_FUNC = ctypes.WINFUNCTYPE(
    HRESULT_T,
    PVOID,
    ctypes.POINTER(ctypes.c_wchar_p),
    ctypes.POINTER(PROPVARIANT),
    ctypes.c_uint32,
)


def write_7z(output_path: Path, entries: list[ArchiveEntryInput], dll_path: Path, compression_level: int = 9) -> None:
    """Create a new 7z archive containing *entries*."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    archive = create_out_archive(CLSID_7z, dll_path)
    properties = archive.query_interface(IID_ISetProperties)
    names = (ctypes.c_wchar_p * 1)("x")
    values = (PROPVARIANT * 1)()
    values[0].vt = VT_UI4
    values[0]._data.ulVal = compression_level
    set_properties = _SET_PROPERTIES_FUNC(properties.vtable[3])
    check_hr(set_properties(properties.raw, names, values, 1), "ISetProperties::SetProperties")

    output_stream = FileOutStream(output_path)
    callback = UpdateCallback(entries)
    try:
        update_items = _UPDATE_ITEMS_FUNC(archive.vtable[3])
        check_hr(
            update_items(archive.raw, output_stream.as_void_p, len(entries), callback.as_void_p),
            "IOutArchive::UpdateItems",
        )
    finally:
        output_stream.close()
        for stream in getattr(callback, "_active_streams", []):
            stream.close()
