# Minecraft Modpack Installer

A standard-library-only Python installer for managed Fabric modpacks. It:

- installs the pack's configured Fabric/Minecraft version;
- copies `Content/` into an isolated instance directory;
- creates or updates an official Minecraft Launcher profile;
- configures the profile with 8-12 GB of memory by default;
- fetches the available catalog and requested modpack from a distribution server;
- retains a local-catalog override for development and testing.

Close Minecraft Launcher before installing so it does not overwrite
`launcher_profiles.json` while the installer updates it.

## Pack Layout

```text
Modpack-Configs/
  My-Pack/
    fabric-installer-1.1.1.exe
    Content/
      mods/
      config/
      resourcepacks/
```

Add each pack to `modpacks.json`. Use an exact `fabric_loader_version` for
reproducible installs, or `latest` to let the bundled Fabric installer select it.

## Distribution Server

Edit `distribution_server.json` and set a strong shared `auth_token`. The server
reads `modpacks.json`, removes server-only source paths from the public catalog,
and exposes:

- `GET /health`
- `GET /api/modpacks`
- `GET /api/modpacks/<id>/download`

Download ZIPs are generated on demand and cached. Changing any file in a pack
automatically creates a fresh cached package on its next request.
The server refuses to start while the example `change-this-token` value remains.

Run the server:

```powershell
python modpack_distribution_server.py
```

On Windows, run it at boot using Task Scheduler with the project directory as
**Start in** and `modpack_distribution_server.py` as the Python argument. Allow
TCP port `8770` only from the intended LAN or VPN.

## Client

Edit `installer_client.json` on client computers with the server address and the
same token:

```json
{
  "catalog_url": "http://server-address:8770/api/modpacks",
  "auth_token": "your-shared-token"
}
```

Python 3.10 or newer and Java must be installed.

```powershell
python modpack_installer.py --list
python modpack_installer.py super-awesome-modpack
```

Validate the full flow without changing Minecraft files:

```powershell
python modpack_installer.py super-awesome-modpack --dry-run
```

Useful overrides:

```powershell
python modpack_installer.py super-awesome-modpack --java "C:\Path\To\java.exe"
python modpack_installer.py super-awesome-modpack --minecraft-dir "D:\Minecraft"
```

For development, bypass `installer_client.json` with a local catalog:

```powershell
python modpack_installer.py super-awesome-modpack --catalog modpacks.json --dry-run
```

This service uses plain HTTP with a shared token. Keep it on a trusted LAN or VPN,
or place it behind an HTTPS reverse proxy before exposing it outside that network.
