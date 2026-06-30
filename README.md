# DennisNap Client

Shares your local music folders with a DennisNap server. Scans directories for music files, registers with the server, and serves files for direct download by other users.

## How it works

- You choose which music folders to share via the web UI
- The scanner finds `.mp3` files in those folders and sends their metadata (filename, size, bitrate) to the server
- The client runs an HTTP server that serves actual audio files for download
- Other users' downloads are proxied through the server, which fetches the file from this client

## Quick start

```bash
docker compose up -d
```

The client listens on **port 40091** (map to container port 5000).

## Web UI

Open `http://<client-host>:40091/` for the configuration and folder picker.

| Section        | Description                                         |
|----------------|-----------------------------------------------------|
| Configuration  | Server URL, username, and download URL              |
| Folder Picker  | Browse your music directories and select folders to share |
| Shared Files   | Table of files currently being shared               |
| Status         | Connection status and file count                    |

## Configuration

Set these environment variables in `docker-compose.yml`:

| Variable       | Default                              | Description                                      |
|----------------|--------------------------------------|--------------------------------------------------|
| `SERVER_URL`   | `http://host.docker.internal:40090`  | URL of the DennisNap server                      |
| `DOWNLOAD_URL` | *(empty)*                            | **Your external-facing URL** (see below)         |
| `USERNAME`     | *(empty)*                            | Username for this client (set via web UI)        |

Music directories are bind-mounted as volumes (e.g., `/media/asustor/Plex/Music:/music:ro`).

The `host.docker.internal` alias is added via `extra_hosts` so Linux Docker hosts can reach the server on the host machine.

## Important: External-facing DOWNLOAD_URL

**The `DOWNLOAD_URL` must be set to an address that other users on the internet can reach.** This is the URL the server's proxy will use to fetch files from this client.

- If the client is on the same LAN as the server, use the client's LAN IP (e.g., `http://192.168.1.11:40091`)
- If clients are on different networks, the client port (40091) must be port-forwarded through NAT/firewall, and `DOWNLOAD_URL` should be the public address (e.g., `http://your-public-ip:40091`)
- If both server and client are behind the same Cloudflare tunnel or reverse proxy, the download URL can be the internal LAN address since the server proxies internally

Each client instance = one user. Deploy additional compose stacks with different usernames, ports, and download URLs for additional users.
