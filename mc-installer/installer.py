#!/usr/bin/env python3
"""Install managed Fabric modpacks into the official Minecraft launcher."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CATALOG = BASE_DIR / "modpacks.json"
DEFAULT_CLIENT_CONFIG = BASE_DIR / "installer_client.json"


def default_minecraft_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / ".minecraft"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/minecraft"
    return Path.home() / ".minecraft"


def load_json_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def load_client_config(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    return load_json_file(resolved) if resolved.is_file() else {}


def auth_headers(auth_token: str | None) -> dict[str, str]:
    return {"X-Auth-Token": auth_token} if auth_token else {}


def load_catalog(catalog: str, auth_token: str | None = None) -> tuple[dict[str, Any], Path | str]:
    parsed = urllib.parse.urlparse(catalog)
    if parsed.scheme in ("http", "https"):
        request = urllib.request.Request(catalog, headers=auth_headers(auth_token))
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8")), catalog
    path = Path(catalog).expanduser().resolve()
    return load_json_file(path), path.parent


def validate_catalog(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    packs = catalog.get("modpacks")
    if not isinstance(packs, list) or not packs:
        raise ValueError("Catalog must contain a non-empty 'modpacks' list.")

    required = {"id", "name", "minecraft_version", "fabric_installer"}
    seen: set[str] = set()
    for pack in packs:
        missing = required - pack.keys()
        if missing:
            raise ValueError(f"Modpack is missing required fields: {', '.join(sorted(missing))}")
        if pack["id"] in seen:
            raise ValueError(f"Duplicate modpack id: {pack['id']}")
        if not pack.get("source") and not pack.get("package_url"):
            raise ValueError(f"Modpack {pack['id']} needs 'source' or 'package_url'.")
        seen.add(pack["id"])
    return packs


def choose_pack(packs: list[dict[str, Any]], requested_id: str | None) -> dict[str, Any]:
    if requested_id:
        for pack in packs:
            if pack["id"] == requested_id:
                return pack
        raise ValueError(f"Unknown modpack id: {requested_id}")

    print("Available modpacks:\n")
    for index, pack in enumerate(packs, start=1):
        print(f"{index}. {pack['name']} (Minecraft {pack['minecraft_version']})")
    while True:
        choice = input("\nSelect modpack number: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(packs):
            return packs[int(choice) - 1]
        print("Enter one of the listed numbers.")


def resolve_local_source(source: str, catalog_base: Path | str) -> Path | None:
    if isinstance(catalog_base, str):
        return None
    path = Path(source).expanduser()
    return (catalog_base / path).resolve() if not path.is_absolute() else path.resolve()


def safe_extract_zip(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            target = (destination / member.filename).resolve()
            if destination != target and destination not in target.parents:
                raise ValueError(f"Unsafe path in modpack archive: {member.filename}")
        package.extractall(destination)


def download_file(url: str, destination: Path, auth_token: str | None = None) -> None:
    request = urllib.request.Request(url, headers=auth_headers(auth_token))
    with urllib.request.urlopen(request, timeout=300) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)


def acquire_pack(
    pack: dict[str, Any], catalog_base: Path | str, temp_dir: Path, auth_token: str | None = None
) -> Path:
    source = pack.get("source")
    if source:
        local_source = resolve_local_source(source, catalog_base)
        if local_source and local_source.is_dir():
            return local_source

    package_url = pack.get("package_url")
    if not package_url:
        raise FileNotFoundError(f"Local source for {pack['id']} was not found and no package_url is set.")

    if isinstance(catalog_base, str):
        package_url = urllib.parse.urljoin(catalog_base, package_url)
    print(f"Downloading {pack['name']}...")
    archive = temp_dir / "modpack.zip"
    download_file(package_url, archive, auth_token)
    extracted = temp_dir / "package"
    extracted.mkdir()
    safe_extract_zip(archive, extracted)

    expected = extracted / pack.get("archive_root", "")
    if not expected.is_dir():
        raise FileNotFoundError(f"Archive root does not exist: {pack.get('archive_root', '')}")
    return expected


def find_java(explicit_java: str | None) -> str:
    if explicit_java:
        return explicit_java
    java = shutil.which("java")
    if java:
        return java
    raise FileNotFoundError("Java was not found on PATH. Pass its path with --java.")


def install_fabric(
    pack: dict[str, Any],
    pack_root: Path,
    minecraft_dir: Path,
    java: str | None,
    dry_run: bool = False,
) -> None:
    installer = pack_root / pack["fabric_installer"]
    if not installer.is_file():
        raise FileNotFoundError(f"Fabric installer not found: {installer}")

    if installer.suffix.lower() == ".exe":
        command = [str(installer)]
    else:
        command = [find_java(java), "-jar", str(installer)]
    command.extend([
        "client",
        "-dir",
        str(minecraft_dir),
        "-mcversion",
        str(pack["minecraft_version"]),
        "-noprofile",
    ])
    loader_version = pack.get("fabric_loader_version")
    if loader_version and loader_version != "latest":
        command.extend(["-loader", str(loader_version)])

    print("Installing Fabric...")
    if dry_run:
        print("DRY RUN:", subprocess.list2cmdline(command))
        return
    minecraft_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(command, check=True)


def locate_fabric_version(minecraft_dir: Path, minecraft_version: str, loader_version: str | None) -> str:
    versions_dir = minecraft_dir / "versions"
    if loader_version and loader_version != "latest":
        exact = f"fabric-loader-{loader_version}-{minecraft_version}"
        if (versions_dir / exact / f"{exact}.json").is_file():
            return exact

    candidates = [
        path.parent.name
        for path in versions_dir.glob(f"fabric-loader-*-{minecraft_version}/*.json")
        if path.stem == path.parent.name
    ]
    if not candidates:
        raise FileNotFoundError(
            f"Fabric installed, but no Fabric version for Minecraft {minecraft_version} was found."
        )
    return max(candidates, key=lambda name: (versions_dir / name).stat().st_mtime)


def copy_content(pack_root: Path, instance_dir: Path, dry_run: bool = False) -> None:
    content = pack_root / "Content"
    if not content.is_dir():
        raise FileNotFoundError(f"Modpack Content directory not found: {content}")
    print(f"Copying modpack content to {instance_dir}...")
    if not dry_run:
        instance_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(content, instance_dir, dirs_exist_ok=True)


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(value, output, indent=2)
        output.write("\n")
    os.replace(temporary, path)


def write_launcher_profile(
    pack: dict[str, Any],
    minecraft_dir: Path,
    instance_dir: Path,
    version_id: str,
    dry_run: bool = False,
) -> None:
    profiles_path = minecraft_dir / "launcher_profiles.json"
    launcher_data = load_json_file(profiles_path) if profiles_path.is_file() else {"profiles": {}}
    profiles = launcher_data.setdefault("profiles", {})
    if not isinstance(profiles, dict):
        raise ValueError("launcher_profiles.json contains an invalid 'profiles' value.")

    memory_min = int(pack.get("memory_min_gb", 8))
    memory_max = int(pack.get("memory_max_gb", 12))
    if memory_min <= 0 or memory_max < memory_min:
        raise ValueError("Memory settings must be positive and max must be at least min.")

    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    profile_id = pack.get("profile_id", f"managed-{pack['id']}")
    profiles[profile_id] = {
        "created": profiles.get(profile_id, {}).get("created", now),
        "gameDir": str(instance_dir),
        "javaArgs": f"-Xms{memory_min}G -Xmx{memory_max}G",
        "lastUsed": now,
        "lastVersionId": version_id,
        "name": pack.get("profile_name", pack["name"]),
        "type": "custom",
    }
    print(f"Creating Minecraft Launcher profile '{profiles[profile_id]['name']}'...")
    if not dry_run:
        atomic_write_json(profiles_path, launcher_data)


def install_pack(
    pack: dict[str, Any],
    catalog_base: Path | str,
    minecraft_dir: Path,
    instances_dir: Path,
    java: str | None,
    dry_run: bool,
    auth_token: str | None = None,
) -> None:
    with tempfile.TemporaryDirectory(prefix="mc-modpack-") as temporary:
        pack_root = acquire_pack(pack, catalog_base, Path(temporary), auth_token)
        instance_dir = (instances_dir / pack["id"]).resolve()
        copy_content(pack_root, instance_dir, dry_run)
        install_fabric(pack, pack_root, minecraft_dir, java, dry_run)
        version_id = (
            f"fabric-loader-DRY-RUN-{pack['minecraft_version']}"
            if dry_run
            else locate_fabric_version(
                minecraft_dir, str(pack["minecraft_version"]), pack.get("fabric_loader_version")
            )
        )
        write_launcher_profile(pack, minecraft_dir, instance_dir, version_id, dry_run)
        print(f"\nInstalled {pack['name']}. Open Minecraft Launcher and select its new profile.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Install managed Fabric modpacks.")
    parser.add_argument("modpack", nargs="?", help="Modpack id; omit for an interactive menu")
    parser.add_argument("--config", type=Path, default=DEFAULT_CLIENT_CONFIG)
    parser.add_argument("--catalog", help="Override the configured local path or HTTP(S) catalog URL")
    parser.add_argument("--list", action="store_true", help="List available modpacks and exit")
    parser.add_argument("--minecraft-dir", type=Path, default=default_minecraft_dir())
    parser.add_argument("--instances-dir", type=Path, help="Defaults to <minecraft-dir>/instances")
    parser.add_argument("--java", help="Path to Java executable")
    parser.add_argument(
        "--auth-token",
        default=None,
        help="Shared distribution-server token; defaults to MODPACK_AUTH_TOKEN",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate and print actions without changing files")
    args = parser.parse_args()

    try:
        client_config = load_client_config(args.config)
        catalog_location = (
            args.catalog
            or os.environ.get("MODPACK_CATALOG_URL")
            or client_config.get("catalog_url")
            or str(DEFAULT_CATALOG)
        )
        auth_token = (
            args.auth_token
            or os.environ.get("MODPACK_AUTH_TOKEN")
            or client_config.get("auth_token")
        )
        catalog, catalog_base = load_catalog(catalog_location, auth_token)
        packs = validate_catalog(catalog)
        if args.list:
            for pack in packs:
                print(f"{pack['id']}: {pack['name']} (Minecraft {pack['minecraft_version']})")
            return
        pack = choose_pack(packs, args.modpack)
        minecraft_dir = args.minecraft_dir.expanduser().resolve()
        instances_dir = (
            args.instances_dir.expanduser().resolve()
            if args.instances_dir
            else minecraft_dir / "instances"
        )
        install_pack(
            pack, catalog_base, minecraft_dir, instances_dir, args.java, args.dry_run, auth_token
        )
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        OSError,
        subprocess.CalledProcessError,
        ValueError,
        zipfile.BadZipFile,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
