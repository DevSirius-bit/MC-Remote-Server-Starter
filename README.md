# MC Controls by Sirius

Minimal Python client tooling and bundled Minecraft modpack files for controlling a Minecraft server launch workflow.

## Contents

- `mc-client/` - command-line Minecraft control client.
- `mc-server-launch/` - clickable copy of the client launcher script.
- `mc-installer/` - bundled modpack configuration and assets.

## Client Configuration

Copy `client_config.example.json` to `client_config.json` in the client folder you plan to use, then set:

- `server_url` - URL for the control service.
- `auth_token` - token expected by the control service.
- `poll_seconds` - status polling interval.

`client_config.json` is ignored by Git so local server addresses and tokens are not published.

## Run

```powershell
python .\mc-client\mc_start_client.py --config .\mc-client\client_config.json
```

## Public Repository Notes

The included modpack assets contain third-party files. Verify each mod/resource license before publishing or redistributing.

GitHub rejects individual files over 100 MB. The Cobblemon jar is ignored by default and should be distributed through Git LFS, a release artifact, or a modpack manifest.
