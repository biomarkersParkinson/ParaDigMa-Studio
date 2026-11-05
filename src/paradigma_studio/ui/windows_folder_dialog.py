"""Windows' standard multi-folder picker, using the system COM API.

The interface layouts and flags are defined by Windows SDK shobjidl.h:
https://learn.microsoft.com/windows/win32/api/shobjidl_core/nn-shobjidl_core-ifileopendialog
No third-party COM runtime or custom file-browser widgets are required.
"""

from __future__ import annotations

import ctypes
from typing import Any, cast
from uuid import UUID

HRESULT = ctypes.c_int32
DWORD = ctypes.c_uint32
POINTER = ctypes.c_void_p
OUT_POINTER = ctypes.POINTER(POINTER)
CANCELLED = 0x800704C7
# FOS_NOCHANGEDIR | PICKFOLDERS | FORCEFILESYSTEM | ALLOWMULTISELECT | PATHMUSTEXIST
FOLDER_OPTIONS = 0x8 | 0x20 | 0x40 | 0x200 | 0x800


class GUID(ctypes.Structure):
    _fields_ = [
        ("data1", ctypes.c_uint32),
        ("data2", ctypes.c_uint16),
        ("data3", ctypes.c_uint16),
        ("data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, value: str) -> GUID:
        return cls.from_buffer_copy(UUID(value).bytes_le)


FILE_OPEN_DIALOG = GUID.parse("dc1c5a9c-e88a-4dde-a5a1-60f82a20aef7")
I_FILE_OPEN_DIALOG = GUID.parse("d57c7288-d4ad-4768-be02-9d969532d960")
I_SHELL_ITEM = GUID.parse("43826d1e-e718-42ee-bc55-a1e261c37bfe")


def _check(result: int) -> None:
    if result & 0x80000000:
        raise OSError(f"Windows folder picker failed (HRESULT 0x{result & 0xFFFFFFFF:08X}).")


class _WindowsAPI:
    """Keep dynamically loaded foreign function types at one boundary."""

    def __init__(self) -> None:
        foreign = cast(Any, ctypes)
        self.prototype = foreign.WINFUNCTYPE
        self.ole = foreign.WinDLL("ole32")
        self.shell = foreign.WinDLL("shell32")
        self.ole.CoInitializeEx.argtypes = [POINTER, DWORD]
        self.ole.CoInitializeEx.restype = HRESULT
        self.ole.CoUninitialize.argtypes = []
        self.ole.CoUninitialize.restype = None
        self.ole.CoCreateInstance.argtypes = [
            ctypes.POINTER(GUID),
            POINTER,
            DWORD,
            ctypes.POINTER(GUID),
            OUT_POINTER,
        ]
        self.ole.CoCreateInstance.restype = HRESULT
        self.ole.CoTaskMemFree.argtypes = [POINTER]
        self.ole.CoTaskMemFree.restype = None
        self.shell.SHCreateItemFromParsingName.argtypes = [
            ctypes.c_wchar_p,
            POINTER,
            ctypes.POINTER(GUID),
            OUT_POINTER,
        ]
        self.shell.SHCreateItemFromParsingName.restype = HRESULT

    def call(self, pointer: Any, slot: int, types: tuple[Any, ...], *arguments: Any) -> int:
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(POINTER))).contents
        method = self.prototype(HRESULT, POINTER, *types)(table[slot])
        return int(method(pointer, *arguments))

    def release(self, pointer: Any) -> None:
        if pointer:
            self.call(pointer, 2, ())  # IUnknown::Release (ULONG; result unused).


def _set_directory(api: _WindowsAPI, dialog: Any, directory: str) -> None:
    if not directory:
        return
    item = POINTER()
    try:
        result = api.shell.SHCreateItemFromParsingName(
            directory, None, ctypes.byref(I_SHELL_ITEM), ctypes.byref(item)
        )
        if not result & 0x80000000 and item:
            # An inaccessible remembered location must not prevent browsing elsewhere.
            api.call(dialog, 12, (POINTER,), item)  # IFileDialog::SetFolder
    finally:
        api.release(item)


def _configure(api: _WindowsAPI, dialog: Any, directory: str) -> None:
    options = DWORD()
    _check(api.call(dialog, 10, (ctypes.POINTER(DWORD),), ctypes.byref(options)))
    _check(api.call(dialog, 9, (DWORD,), options.value | FOLDER_OPTIONS))
    _check(api.call(dialog, 17, (ctypes.c_wchar_p,), "Open recording folders for the same subject"))
    _check(api.call(dialog, 18, (ctypes.c_wchar_p,), "Select folders"))
    _set_directory(api, dialog, directory)


def _item_path(api: _WindowsAPI, items: Any, index: int) -> str:
    item, name = POINTER(), POINTER()
    try:
        _check(api.call(items, 8, (DWORD, OUT_POINTER), index, ctypes.byref(item)))
        # SIGDN_FILESYSPATH returns a CoTaskMem-owned UTF-16 string.
        _check(api.call(item, 5, (DWORD, OUT_POINTER), 0x80058000, ctypes.byref(name)))
        if not name:
            raise OSError("Windows did not return a folder path.")
        return ctypes.wstring_at(name)
    finally:
        api.ole.CoTaskMemFree(name)
        api.release(item)


def _selected_paths(api: _WindowsAPI, dialog: Any) -> list[str]:
    items = POINTER()
    try:
        _check(api.call(dialog, 27, (OUT_POINTER,), ctypes.byref(items)))
        count = DWORD()
        _check(api.call(items, 7, (ctypes.POINTER(DWORD),), ctypes.byref(count)))
        return [_item_path(api, items, index) for index in range(count.value)]
    finally:
        api.release(items)


def choose_windows_folders(owner: int, directory: str = "") -> list[str]:
    """Choose folders on the GUI's STA thread; return no paths on cancellation."""
    api = _WindowsAPI()
    # Balance both S_OK and S_FALSE, including when Qt already initialized COM.
    _check(api.ole.CoInitializeEx(None, 2))  # COINIT_APARTMENTTHREADED
    dialog = POINTER()
    try:
        _check(
            api.ole.CoCreateInstance(
                ctypes.byref(FILE_OPEN_DIALOG),
                None,
                1,
                ctypes.byref(I_FILE_OPEN_DIALOG),
                ctypes.byref(dialog),
            )
        )
        _configure(api, dialog, directory)
        result = api.call(dialog, 3, (POINTER,), owner)  # IModalWindow::Show(HWND)
        if result & 0xFFFFFFFF == CANCELLED:
            return []
        _check(result)
        return _selected_paths(api, dialog)
    finally:
        api.release(dialog)
        api.ole.CoUninitialize()
