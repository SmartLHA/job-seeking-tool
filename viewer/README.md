# Local Docs Viewer

This is a simple local web page for browsing the project markdown files in one place.

## Canonical Reed Job Viewer

`reed_jobs_v4.html` is the only retained standalone Reed job viewer. Older variants (`reed_jobs.html`, v2, v3, debug, minimal, and test pages) were removed so links and manual checks point to one file.

## Run locally on your Mac

From this project's folder, run the supported server:

```bash
python3 viewer/viewer_server.py
```

Then open `http://127.0.0.1:8765/viewer/` on the same Mac.
If port 8765 is already occupied, check the existing service before starting another server.

The server binds to loopback by default. Its static file allowlist serves the
viewer assets and the explicitly listed public project documents. Other project
files, directory listings, traversal paths, and symbolic links are not served.
`viewer/documents.json` describes navigation; adding an entry does not grant
access to a file. Public document additions require an explicit server allowlist update.

Network access from other devices is not supported. Use this server rather than
an unrestricted generic file server, which exposes files outside that allowlist.
