# Local Docs Viewer

This is a simple local web page for browsing the project markdown files in one place.

## Canonical Reed Job Viewer

`reed_jobs_v4.html` is the only retained standalone Reed job viewer. Older variants (`reed_jobs.html`, v2, v3, debug, minimal, and test pages) were removed so links and manual checks point to one file.

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
