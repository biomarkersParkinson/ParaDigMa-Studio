"""Exercise COM marshalling and ownership without opening a modal system window."""

import ctypes
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from paradigma_studio.ui import windows_folder_dialog as native


class ShellHarness:
    """Real ctypes vtables implementing the SDK interfaces with controlled results."""

    def __init__(self, *, cancelled=False, failure=None, init_result=0):
        self.cancelled, self.failure, self.init_result = cancelled, failure, init_result
        self.kept, self.released, self.freed, self.events = [], [], [], []
        self.options = 0x1000
        self.paths = [r"C:\recordings\session α", r"\\server\share\session $literal%"]
        self.names = [ctypes.create_unicode_buffer(path) for path in self.paths]
        self.items = [
            self.interface(
                f"item{index}",
                {
                    5: ((native.DWORD, native.OUT_POINTER), self.display_name(index)),
                },
            )
            for index in range(len(self.paths))
        ]
        self.array = self.interface(
            "array",
            {
                7: ((ctypes.POINTER(native.DWORD),), self.get_count),
                8: ((native.DWORD, native.OUT_POINTER), self.get_item),
            },
        )
        self.initial = self.interface("initial", {})
        self.dialog = self.interface(
            "dialog",
            {
                3: ((native.POINTER,), self.show),
                9: ((native.DWORD,), self.set_options),
                10: ((ctypes.POINTER(native.DWORD),), self.get_options),
                12: ((native.POINTER,), self.set_folder),
                17: ((ctypes.c_wchar_p,), self.set_title),
                18: ((ctypes.c_wchar_p,), self.set_label),
                27: ((native.OUT_POINTER,), self.get_results),
            },
        )
        self.api = native._WindowsAPI.__new__(native._WindowsAPI)
        self.api.prototype = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
        self.api.ole = SimpleNamespace(
            CoInitializeEx=self.initialize,
            CoUninitialize=lambda: self.events.append("uninitialize"),
            CoCreateInstance=self.create,
            CoTaskMemFree=lambda pointer: self.freed.append(pointer.value) if pointer else None,
        )
        self.api.shell = SimpleNamespace(SHCreateItemFromParsingName=self.parse_directory)

    def interface(self, name, methods):
        prototype = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
        missing = prototype(native.HRESULT, native.POINTER)(lambda _this: -2147467263)
        table = (native.POINTER * 29)(*[ctypes.cast(missing, native.POINTER).value] * 29)
        methods = {**methods, 2: ((), lambda _this: self.released.append(name) or 0)}
        for slot, (types, method) in methods.items():
            callback = prototype(native.HRESULT, native.POINTER, *types)(method)
            table[slot] = ctypes.cast(callback, native.POINTER).value
            self.kept.append(callback)
        instance = (native.POINTER * 1)(ctypes.cast(table, native.POINTER).value)
        self.kept.extend([missing, table, instance])
        return ctypes.cast(instance, native.POINTER)

    def initialize(self, reserved, flags):
        assert reserved is None and flags == 2
        self.events.append("initialize")
        return self.init_result

    def create(self, clsid, outer, context, interface, output):
        assert ctypes.string_at(clsid, 16) == UUID("dc1c5a9c-e88a-4dde-a5a1-60f82a20aef7").bytes_le
        assert (
            ctypes.string_at(interface, 16) == UUID("d57c7288-d4ad-4768-be02-9d969532d960").bytes_le
        )
        assert outer is None and context == 1
        if self.failure == "create":
            return -2147467259
        ctypes.cast(output, native.OUT_POINTER)[0] = self.dialog.value
        return 0

    def get_options(self, _this, output):
        output[0] = self.options
        return 0

    def set_options(self, _this, value):
        self.options = value
        return -2147467259 if self.failure == "options" else 0

    def set_title(self, _this, title):
        self.title = title
        return 0

    def set_label(self, _this, label):
        self.label = label
        return 0

    def parse_directory(self, directory, context, interface, output):
        assert context is None
        assert (
            ctypes.string_at(interface, 16) == UUID("43826d1e-e718-42ee-bc55-a1e261c37bfe").bytes_le
        )
        self.directory = directory
        if self.failure == "initial":
            return -2147467259
        ctypes.cast(output, native.OUT_POINTER)[0] = self.initial.value
        return 0

    def set_folder(self, _this, pointer):
        self.folder_pointer = pointer
        return 0

    def show(self, _this, owner):
        self.owner = owner
        self.events.append("show")
        return -2147023673 if self.cancelled else 0  # HRESULT_FROM_WIN32(ERROR_CANCELLED)

    def get_results(self, _this, output):
        output[0] = self.array.value
        return 0

    def get_count(self, _this, output):
        output[0] = len(self.items)
        return 0

    def get_item(self, _this, index, output):
        output[0] = self.items[index].value
        return 0

    def display_name(self, index):
        def result(_this, kind, output):
            assert kind == 0x80058000
            if self.failure == "name" and index == 1:
                return -2147467259
            if self.failure != "null-name":
                output[0] = ctypes.cast(self.names[index], native.POINTER).value
            return 0

        return result


@pytest.mark.parametrize("init_result", [0, 1], ids=["new-com-apartment", "qt-already-initialized"])
def test_native_picker_returns_all_unicode_unc_paths_and_releases_resources(
    monkeypatch, init_result
):
    shell = ShellHarness(init_result=init_result)
    monkeypatch.setattr(native, "_WindowsAPI", lambda: shell.api)
    assert native.choose_windows_folders(2**40 + 7, r"C:\recordings") == shell.paths
    assert shell.owner == 2**40 + 7
    assert shell.options & (0x8 | 0x20 | 0x40 | 0x200 | 0x800) == (
        0x8 | 0x20 | 0x40 | 0x200 | 0x800
    )
    assert shell.options & 0x1000  # Retain system defaults too.
    assert shell.folder_pointer == shell.initial.value
    assert shell.label == "Select folders"
    assert shell.freed == [ctypes.cast(name, native.POINTER).value for name in shell.names]
    assert shell.released == ["initial", "item0", "item1", "array", "dialog"]
    assert shell.events == ["initialize", "show", "uninitialize"]


def test_native_cancel_returns_no_paths_and_still_balances_com(monkeypatch):
    shell = ShellHarness(cancelled=True)
    monkeypatch.setattr(native, "_WindowsAPI", lambda: shell.api)
    assert native.choose_windows_folders(0) == []
    assert shell.released == ["dialog"] and not shell.freed
    assert shell.events[-1] == "uninitialize"


@pytest.mark.parametrize("failure", ["create", "options", "name", "null-name"])
def test_native_failures_release_partial_results_without_returning_partial_paths(
    monkeypatch, failure
):
    shell = ShellHarness(failure=failure)
    monkeypatch.setattr(native, "_WindowsAPI", lambda: shell.api)
    with pytest.raises(OSError):
        native.choose_windows_folders(0)
    assert shell.events[-1] == "uninitialize"
    if failure != "create":
        assert "dialog" in shell.released
    if failure == "name":
        assert shell.released == ["item0", "item1", "array", "dialog"]
        assert len(shell.freed) == 1


def test_missing_remembered_folder_keeps_system_picker_usable(monkeypatch):
    shell = ShellHarness(failure="initial")
    monkeypatch.setattr(native, "_WindowsAPI", lambda: shell.api)
    assert native.choose_windows_folders(0, r"C:\deleted") == shell.paths
    assert "initial" not in shell.released and shell.events[-1] == "uninitialize"


def test_failed_com_initialization_is_not_uninitialized(monkeypatch):
    shell = ShellHarness(init_result=-2147417850)
    monkeypatch.setattr(native, "_WindowsAPI", lambda: shell.api)
    with pytest.raises(OSError, match="80010106"):
        native.choose_windows_folders(0)
    assert shell.events == ["initialize"] and not shell.released


@pytest.mark.skipif(
    sys.platform != "win32", reason="Exercises real Windows COM without showing UI."
)
def test_real_windows_shell_configuration_and_filesystem_item_abi(tmp_path):
    assert ctypes.sizeof(native.GUID) == 16
    folder = tmp_path / "Session α $literal%"
    folder.mkdir()
    # Use a fresh STA, independent of other libraries' COM use in the test runner.
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(check_real_shell_configuration, folder).result(timeout=10)


def check_real_shell_configuration(folder):
    api = native._WindowsAPI()
    native._check(api.ole.CoInitializeEx(None, 2))
    dialog, item, name = native.POINTER(), native.POINTER(), native.POINTER()
    try:
        native._check(
            api.ole.CoCreateInstance(
                ctypes.byref(native.FILE_OPEN_DIALOG),
                None,
                1,
                ctypes.byref(native.I_FILE_OPEN_DIALOG),
                ctypes.byref(dialog),
            )
        )
        native._configure(api, dialog, str(folder))
        flags = native.DWORD()
        native._check(api.call(dialog, 10, (ctypes.POINTER(native.DWORD),), ctypes.byref(flags)))
        assert flags.value & native.FOLDER_OPTIONS == native.FOLDER_OPTIONS
        native._check(api.call(dialog, 13, (native.OUT_POINTER,), ctypes.byref(item)))
        native._check(
            api.call(item, 5, (native.DWORD, native.OUT_POINTER), 0x80058000, ctypes.byref(name))
        )
        assert Path(ctypes.wstring_at(name)) == folder
    finally:
        api.ole.CoTaskMemFree(name)
        api.release(item)
        api.release(dialog)
        api.ole.CoUninitialize()
