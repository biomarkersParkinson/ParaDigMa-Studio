"""Signing policy checks; cryptographic operations require Windows."""

import copy
import os
import struct
import subprocess
import sys

import pytest

from scripts.signing_bundle import (
    make_plan,
    native_files,
    read_signatures,
    refresh_hashes,
    validate_config,
    validate_signed,
    validate_unchanged_assets,
)


def signature(path, signed=False, subject="CN=Example Publisher"):
    return {
        "path": path,
        "status": "Valid" if signed else "NotSigned",
        "signature_type": "Authenticode" if signed else "None",
        "subject": subject if signed else None,
        "thumbprint": "example" if signed else None,
        "timestamp_subject": "CN=Timestamp" if signed else None,
        "sha256": "before",
    }


def config():
    return {
        "AZURE_CLIENT_ID": "11111111-1111-1111-1111-111111111111",
        "AZURE_TENANT_ID": "22222222-2222-2222-2222-222222222222",
        "AZURE_SUBSCRIPTION_ID": "33333333-3333-3333-3333-333333333333",
        "SIGNING_ENDPOINT": "https://weu.codesigning.azure.net/",
        "SIGNING_ACCOUNT_NAME": "example-account",
        "SIGNING_CERTIFICATE_PROFILE": "example-profile",
        "SIGNING_PUBLISHER_SUBJECT": "CN=Example Publisher",
    }


def test_missing_account_cannot_be_mistaken_for_signed_configuration():
    with pytest.raises(ValueError, match="Configure GitHub environment"):
        validate_config({})
    validate_config(config())


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://weu.codesigning.azure.net/",
        "https://example.com/",
        "https://weu.codesigning.azure.net.example.com/",
        "https://user:password@weu.codesigning.azure.net/",
    ],
)
def test_signing_account_endpoint_is_not_arbitrary(endpoint):
    values = config()
    values["SIGNING_ENDPOINT"] = endpoint
    with pytest.raises(ValueError, match="HTTPS regional"):
        validate_config(values)


def test_native_inventory_includes_hidden_libraries_pyd_and_other_pe_files(tmp_path):
    (tmp_path / "ParaDigMaDesktop.exe").write_bytes(b"MZ")
    libraries = tmp_path / "_internal" / "sklearn" / ".libs"
    libraries.mkdir(parents=True)
    (libraries / "vcomp140.dll").write_bytes(b"MZ")
    (libraries / "extension.pyd").write_bytes(b"MZ")
    header = bytearray(68)
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 60, 64)
    header[64:] = b"PE\0\0"
    (libraries / "native.unusual").write_bytes(header)
    (libraries / "model.pkl").write_bytes(b"not executable")
    assert {file.name for file in native_files(tmp_path)} == {
        "ParaDigMaDesktop.exe",
        "vcomp140.dll",
        "extension.pyd",
        "native.unusual",
    }


def test_existing_vendor_signatures_are_preserved_and_catalog_signatures_are_not_portable():
    vendor = signature("_internal/vendor.dll", True, "CN=Vendor")
    catalog_signed = signature("_internal/catalog.dll", True, "CN=Vendor")
    catalog_signed["signature_type"] = "Catalog"
    plan = make_plan([signature("ParaDigMaDesktop.exe"), vendor, catalog_signed])
    assert [file["path"] for file in plan["files"] if file["needs_signing"]] == [
        "ParaDigMaDesktop.exe",
        "_internal/catalog.dll",
    ]
    invalid = {**vendor, "status": "HashMismatch"}
    with pytest.raises(ValueError, match="invalid or untrusted"):
        make_plan([signature("ParaDigMaDesktop.exe"), invalid])


def test_publisher_timestamp_inventory_and_vendor_integrity_are_required():
    original = [
        signature("ParaDigMaDesktop.exe"),
        signature("_internal/vendor.dll", True, "CN=Vendor"),
    ]
    plan = make_plan(original)
    signed = [signature("ParaDigMaDesktop.exe", True), original[1]]
    validate_signed(plan, signed, "CN=Example Publisher")
    for field, value in [("subject", "CN=Different Publisher"), ("timestamp_subject", None)]:
        changed = copy.deepcopy(signed)
        changed[0][field] = value
        with pytest.raises(ValueError, match="Publisher or trusted timestamp"):
            validate_signed(plan, changed, "CN=Example Publisher")
    with pytest.raises(ValueError, match="inventory changed"):
        validate_signed(plan, signed[:1], "CN=Example Publisher")
    changed = copy.deepcopy(signed)
    changed[1]["sha256"] = "changed"
    with pytest.raises(ValueError, match="vendor-signed file changed"):
        validate_signed(plan, changed, "CN=Example Publisher")
    changed[1]["status"] = "NotTrusted"
    with pytest.raises(ValueError, match="Missing valid embedded"):
        validate_signed(plan, changed, "CN=Example Publisher")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Authenticode API required")
def test_windows_reads_real_unsigned_assembly_and_pyd_signatures(tmp_path):
    # Compile an actual unsigned PE assembly. No signing identity or fake
    # certificates are used; this exercises the real Windows signature API.
    library = tmp_path / "probe.dll"
    subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Add-Type -TypeDefinition 'public class SigningProbe { public static int Answer = 42; }' "
            "-OutputAssembly $env:PARADIGMA_SIGNING_TEST_ASSEMBLY",
        ],
        env={**os.environ, "PARADIGMA_SIGNING_TEST_ASSEMBLY": str(library)},
        check=True,
        timeout=60,
    )
    (tmp_path / "ParaDigMaDesktop.exe").write_bytes(library.read_bytes())
    (tmp_path / "probe.pyd").write_bytes(library.read_bytes())
    entries = read_signatures(tmp_path)
    assert len(entries) == 3
    assert all(entry["status"] == "NotSigned" for entry in entries)
    assert len(make_plan(entries)["files"]) == 3


@pytest.mark.parametrize("change", ["modify", "remove", "add"])
def test_signing_cannot_alter_or_remove_classifier_assets(tmp_path, change):
    model = tmp_path / "model.pkl"
    model.write_bytes(b"original model")
    refresh_hashes(tmp_path)
    plan = {"files": []}
    validate_unchanged_assets(tmp_path, plan)
    if change == "modify":
        model.write_bytes(b"changed model")
    elif change == "remove":
        model.unlink()
    else:
        (tmp_path / "injected.py").write_bytes(b"unexpected code")
    with pytest.raises(ValueError, match="bundle asset"):
        validate_unchanged_assets(tmp_path, plan)
