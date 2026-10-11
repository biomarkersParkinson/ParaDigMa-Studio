"""Plan/verify Windows publisher signing without handling private keys."""

import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

CONFIG_NAMES = (
    "AZURE_CLIENT_ID",
    "AZURE_TENANT_ID",
    "AZURE_SUBSCRIPTION_ID",
    "SIGNING_ENDPOINT",
    "SIGNING_ACCOUNT_NAME",
    "SIGNING_CERTIFICATE_PROFILE",
    "SIGNING_PUBLISHER_SUBJECT",
)


def validate_config(environment):
    missing = [name for name in CONFIG_NAMES if not environment.get(name, "").strip()]
    if missing:
        raise ValueError(
            "Configure GitHub environment windows-signing first; missing: " + ", ".join(missing)
        )
    if any(character in environment["SIGNING_PUBLISHER_SUBJECT"] for character in ("\n", "\r")):
        raise ValueError("SIGNING_PUBLISHER_SUBJECT must be a single certificate subject line.")
    for name in CONFIG_NAMES[:3]:
        try:
            UUID(environment[name])
        except ValueError as error:
            raise ValueError(f"{name} must be an Azure GUID.") from error
    endpoint = urlparse(environment["SIGNING_ENDPOINT"])
    if (
        endpoint.scheme != "https"
        or not (endpoint.hostname or "").endswith(".codesigning.azure.net")
        or endpoint.username
        or endpoint.password
        or endpoint.port
        or endpoint.path not in ("", "/")
        or endpoint.query
        or endpoint.fragment
    ):
        raise ValueError(
            "SIGNING_ENDPOINT must be the HTTPS regional codesigning.azure.net endpoint."
        )


def native_files(bundle):
    """Include known native extensions, hidden libraries and other PE files."""
    bundle = Path(bundle).resolve()
    paths = []
    for path in sorted(bundle.rglob("*")):
        if path.is_symlink():
            raise ValueError("Signing input must not contain symlinks.")
        if not path.is_file():
            continue
        native = path.suffix.lower() in {".exe", ".dll", ".pyd"}
        if not native:
            with path.open("rb") as stream:
                header = stream.read(64)
                if len(header) == 64 and header[:2] == b"MZ":
                    stream.seek(struct.unpack_from("<I", header, 60)[0])
                    native = stream.read(4) == b"PE\0\0"
        if native:
            relative = path.relative_to(bundle).as_posix()
            if any(character in relative for character in ("\n", "\r", ",")):
                raise ValueError("A native filename cannot be represented in the signing catalog.")
            paths.append(path)
    if not paths or not (bundle / "ParaDigMaStudio.exe").is_file():
        raise ValueError(
            "Signing input must include ParaDigMaStudio.exe and its native dependencies."
        )
    return paths


def read_signatures(bundle):
    if sys.platform != "win32":
        raise RuntimeError("Authenticode checks require Windows and PowerShell 7.")
    bundle = Path(bundle).resolve()
    paths = native_files(bundle)
    with tempfile.TemporaryDirectory(prefix="paradigma-signatures-") as directory:
        inventory = Path(directory) / "inventory.json"
        report = Path(directory) / "signatures.json"
        inventory.write_text(
            json.dumps(
                [
                    {"path": path.relative_to(bundle).as_posix(), "absolute_path": str(path)}
                    for path in paths
                ]
            ),
            encoding="utf-8",
        )
        subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(Path(__file__).with_name("windows_signatures.ps1")),
                "-Inventory",
                str(inventory),
                "-Report",
                str(report),
            ],
            check=True,
            timeout=180,
        )
        records = json.loads(report.read_text(encoding="utf-8-sig"))
    by_path = {entry["path"]: entry for entry in records}
    if len(by_path) != len(paths) or set(by_path) != {
        path.relative_to(bundle).as_posix() for path in paths
    }:
        raise ValueError("Windows signature report does not cover every native file.")
    for path in paths:
        with path.open("rb") as stream:
            by_path[path.relative_to(bundle).as_posix()]["sha256"] = hashlib.file_digest(
                stream, "sha256"
            ).hexdigest()
    return records


def make_plan(records):
    if len({record["path"] for record in records}) != len(records):
        raise ValueError("Duplicate paths in signature inventory.")
    planned = []
    for record in records:
        status = record["status"]
        if status not in {"Valid", "NotSigned"}:
            raise ValueError(
                f"Refusing to sign an invalid or untrusted existing signature: {record['path']} ({status})"
            )
        # A catalog on the runner's OS is not part of the portable bundle.
        needs_signing = status == "NotSigned" or record["signature_type"] != "Authenticode"
        planned.append({**record, "needs_signing": needs_signing})
    if not any(record["needs_signing"] for record in planned):
        raise ValueError("No files need signing; provide a fresh unsigned build.")
    return {"files": planned}


def validate_signed(plan, records, publisher):
    original = {entry["path"]: entry for entry in plan["files"]}
    current = {entry["path"]: entry for entry in records}
    if len(current) != len(records) or set(original) != set(current):
        raise ValueError("Native file inventory changed during signing.")
    for name, entry in current.items():
        if entry["status"] != "Valid" or entry["signature_type"] != "Authenticode":
            raise ValueError(f"Missing valid embedded Authenticode signature: {name}")
        if original[name]["needs_signing"] or name == "ParaDigMaStudio.exe":
            if entry["subject"] != publisher or not entry["timestamp_subject"]:
                raise ValueError(f"Publisher or trusted timestamp mismatch: {name}")
        else:
            if (
                entry["sha256"] != original[name]["sha256"]
                or entry["thumbprint"] != original[name]["thumbprint"]
            ):
                raise ValueError(f"An existing vendor-signed file changed: {name}")


def verify_with_signtool(bundle, records):
    kits = Path(os.environ["PROGRAMFILES(X86)"]) / "Windows Kits" / "10" / "bin"
    candidates = list(kits.glob("*/x64/signtool.exe"))
    if not candidates:
        raise RuntimeError("Install the Windows SDK signing tools to verify Authenticode chains.")
    tool = max(
        candidates, key=lambda path: tuple(int(part) for part in path.parent.parent.name.split("."))
    )
    # Batches keep the command below Windows' command-line length limit.
    batch = []
    length = 0
    for entry in records:
        path = str(Path(bundle).resolve() / entry["path"])
        if batch and length + len(path) > 15000:
            _verify_batch(tool, batch)
            batch, length = [], 0
        batch.append(path)
        length += len(path) + 3
    _verify_batch(tool, batch)


def _verify_batch(tool, paths):
    result = subprocess.run(
        [str(tool), "verify", "/pa", "/all", *paths], capture_output=True, text=True, timeout=180
    )
    if result.returncode:
        raise RuntimeError("SignTool rejected a signature chain:\n" + result.stdout + result.stderr)


def refresh_hashes(bundle):
    bundle = Path(bundle).resolve()
    lines = []
    for path in sorted(bundle.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            lines.append(f"{digest}  {path.relative_to(bundle).as_posix()}\n")
    (bundle / "SHA256SUMS.txt").write_text("".join(lines), encoding="utf-8")


def validate_unchanged_assets(bundle, plan):
    """Signing must not change classifier pickles, resources or provenance."""
    bundle = Path(bundle).resolve()
    natives = {entry["path"] for entry in plan["files"]}
    entries = [
        line.split("  ", 1)
        for line in (bundle / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    ]
    reports = {"security/signing-plan.json", "security/windows-signatures.json"}
    actual = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS.txt"
    } - reports
    if actual != {name for _, name in entries} - reports:
        raise ValueError("The bundle asset inventory changed during signing.")
    for expected, name in entries:
        if name in natives or name in reports:
            continue
        path = (bundle / name).resolve()
        if not path.is_relative_to(bundle) or not path.is_file():
            raise ValueError(f"A bundle asset disappeared or is outside the bundle: {name}")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError(f"A non-native bundle asset changed during signing: {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("config", "plan", "verify"))
    parser.add_argument("bundle", nargs="?")
    parser.add_argument("--catalog")
    args = parser.parse_args()
    if args.mode == "config":
        validate_config(os.environ)
        if os.environ.get("GITHUB_OUTPUT"):
            with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
                stream.write(
                    "publisher_subject=" + os.environ["SIGNING_PUBLISHER_SUBJECT"].strip() + "\n"
                )
        print("Signing configuration is present. Publisher verification remains enforced by Azure.")
        return
    if not args.bundle:
        parser.error("bundle is required for plan/verify")
    bundle = Path(args.bundle).resolve()
    security = bundle / "security"
    security.mkdir(exist_ok=True)
    plan_path = security / "signing-plan.json"
    if args.mode == "plan":
        if not args.catalog:
            parser.error("--catalog is required for plan")
        plan = make_plan(read_signatures(bundle))
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        catalog = Path(args.catalog).resolve()
        catalog.write_text(
            "".join(
                os.path.relpath(bundle / entry["path"], catalog.parent) + "\n"
                for entry in plan["files"]
                if entry["needs_signing"]
            ),
            encoding="utf-8",
        )
        print(
            f"Prepared {sum(entry['needs_signing'] for entry in plan['files'])} native files for publisher signing."
        )
    else:
        publisher = os.environ.get("SIGNING_PUBLISHER_SUBJECT", "").strip()
        if not publisher:
            raise ValueError("SIGNING_PUBLISHER_SUBJECT is required for verification.")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        records = read_signatures(bundle)
        validate_signed(plan, records, publisher)
        validate_unchanged_assets(bundle, plan)
        verify_with_signtool(bundle, records)
        (security / "windows-signatures.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "publisher_subject": publisher,
                    "native_files": len(records),
                    "signtool_chain_verification": True,
                    "files": records,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        refresh_hashes(bundle)
        print(f"Verified {len(records)} embedded signatures and refreshed bundle hashes.")


if __name__ == "__main__":
    main()
