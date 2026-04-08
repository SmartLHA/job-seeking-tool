# Local Docs Viewer

This is a simple local web page for browsing the project markdown files in one place.

## Run locally on your Mac

From the project folder:

```bash
cd "/Users/lhaclaw/AI-Project-Workspace/Job Seeking Tool"
python3 -m http.server 8765
```

Then open on the same Mac:

```text
http://localhost:8765/viewer/
```

## View from your mobile phone on the same Wi‑Fi

Run the server so it listens on your local network:

```bash
cd "/Users/lhaclaw/AI-Project-Workspace/Job Seeking Tool"
python3 -m http.server 8765 --bind 0.0.0.0
```

Then find your Mac's local IP address, for example with:

```bash
ipconfig getifaddr en0
```

If that returns nothing, try:

```bash
ipconfig getifaddr en1
```

Then open this on your phone browser:

```text
http://YOUR-MAC-IP:8765/viewer/
```

Example:

```text
http://192.168.1.35:8765/viewer/
```

## Remote access via Tailscale (recommended)

This viewer can be made available remotely behind Tailscale Serve, ideally on a subpath such as:

```text
https://YOUR-TAILSCALE-HOST/job-seeking-tool/viewer/
```

The viewer is now written to be subpath-safe so it can work behind a Tailscale Serve path prefix.

## Notes

- Your phone and Mac must be on the same network for LAN access.
- macOS Firewall may ask you to allow incoming connections for Python.
- The viewer now reads its document list from `viewer/documents.json` instead of a hardcoded JavaScript list.
- To add a newly created project doc to the viewer, update `viewer/documents.json`.
- Use the **Refresh** button after updating project files or the manifest.
- This is intentionally lightweight and local-only unless you deliberately place it behind Tailscale.
