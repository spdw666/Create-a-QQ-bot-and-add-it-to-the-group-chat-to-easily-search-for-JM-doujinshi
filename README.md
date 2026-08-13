# Create a QQ bot and add it to the group chat to easily search for JM doujinshi

A Python QQ group bot (**JM娘**) that lets group members search and download doujinshi
from [jmcomic](https://github.com/tonquer/jmcomic)-supported sources directly in a QQ group chat —
by simply mentioning the bot.

> ⚠️ **Legal disclaimer**: This project is for **educational purposes only**.
> Adult content is involved; you are solely responsible for complying with the laws of
> your region and the terms of service of the platforms involved.
> Using unofficial clients/automation carries a real risk of account bans.
> Do not use this bot for any illegal activity.

## Features

Group members mention the bot (`@bot`) followed by a command:

| Command | What it does |
|---|---|
| `@bot <album ID>` | Downloads the entire doujinshi, packs it into one ZIP, uploads it to the group files and also sends a browser download link |
| `@bot <keyword / title>` | Searches and returns the latest **5 results with IDs** (paginated — see below) |
| `@bot 作者 <author name>` | Searches by **author** and returns 5 results with IDs |
| `@bot 随机` | Random recommendation from the hottest doujinshi of the last 30 days |
| `@bot 下一页` | Next page of the last search result (paginate until all results are seen) |
| `@bot 取消` | Cancels the in-progress download |
| `@bot 说明` | Shows the help text |

Highlights:

- **Smart CJK search** — searching with Simplified Chinese automatically matches
  Traditional Chinese / Japanese kanji / kana titles through a 4-layer fallback:
  1. Simplified → Traditional conversion (`zhconv`)
  2. Hanzi variant map (e.g. `琉 → 瑠`, `绘 → 絵`)
  3. Chinese function words → Japanese kana (e.g. `与/和 → と`, `的/之 → の` — so
     searching `枫与铃` finds `楓と鈴`)
  4. Core-character degraded search: split the query into core characters, search each
     one, and keep titles containing all of them (dictionary-free universal fallback)
- **Paginated results** — 5 per page, `@bot 下一页` pages through all matched albums
- **Encrypted ZIPs (AES-128)** — QQ scans ZIP contents on upload and silently deletes
  adult files; encryption makes the scan fail, so uploads survive (verified:
  unencrypted upload → `retcode=1200`, AES-encrypted → `retcode=0`)
- **Browser download links** — every download also gets an HTTP link as a fallback
- **CQ-code escaping** — user-controlled strings are escaped before being echoed,
  so group members can't make the bot `@all` or send fake images via `[CQ:...]`
- **Per-group rate limiting** — 10 s cooldown on search requests
- **Progress reports** (25/50/75%), queueing (2 concurrent downloads), 7-day auto-cleanup

## Architecture

```
QQ group chat
    │  OneBot v11 (WebSocket)
    ▼
NapCat (QQ bot runtime)  ── ws://127.0.0.1:8081 ──►  JM bot (Python, this repo)
                                                        │
                                        jmcomic ──► download album ──► AES ZIP
                                                        │
                          upload_group_file ──► QQ group files
                          publish token URL  ──► http.server :8080
```

## Requirements

- **NapCat** (or any OneBot v11 implementation) with a QQ account logged in
- Python 3.10+
- Dependencies:

```bash
pip install -r requirements.txt
```

## Setup

### 1. Install NapCat and configure the OneBot WebSocket

Install NapCat for your platform (see the official NapCat docs), log in with the bot's QQ
account (scan the QR code once), then create an OneBot v11 **forward WebSocket server**
listening on `ws://127.0.0.1:8081` (bot connects out to it).
Optionally raise the upload speed limit (`uploadSpeedKBps`) in NapCat's OneBot config.

### 2. Configure the bot

Sensitive values are read from environment variables (never hard-coded):

| Variable | Meaning |
|---|---|
| `JM_ZIP_PASSWORD` | AES password for the uploaded ZIPs (must be shared with users) |
| `JM_PUBLIC_IP` | Public IP/host of this server, used to build browser download links |
| `JM_PROXY` | Optional HTTP proxy for jmcomic, e.g. `http://127.0.0.1:7890` (empty = direct) |

Serve the download directory over HTTP on port 8080:

```bash
mkdir -p http_dl
python3 -m http.server 8080 --bind 0.0.0.0 --directory http_dl
```

### 3. Run

```bash
python jm_niang.py
```

Or as a systemd service (recommended):

```ini
# /etc/systemd/system/jmniang.service
[Unit]
Description=JM Niang QQ Bot (download comic -> zip -> upload)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/jmniang
Environment=JM_ZIP_PASSWORD=YOUR_PASSWORD
Environment=JM_PUBLIC_IP=YOUR_SERVER_IP
ExecStart=/usr/bin/python3 -u /opt/jmniang/jm_niang.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now jmniang
```

### 4. Optional: allow-list groups

Edit `ALLOWED_GROUPS` in `jm_niang.py` to restrict which QQ groups may use the bot
(empty list = all groups).

## Tests

```bash
python -m pytest test_jm_download.py
```

Covers ZIP encryption, CQ escaping, search-variant generation, author command parsing
and pagination rendering (all offline, no network needed).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Bot is silent in the group | The QQ account was likely kicked offline (NapCat stays alive). Quick probe: call `send_group_msg` over the WS; a `retcode=1200 ... NodeIKernelMsgService` timeout means the QQ kernel is dead → restart NapCat and re-scan the QR code |
| Group file upload fails | QQ scans ZIP contents and rejects adult images → keep `ZIP_ENCRYPT = True` (AES-128); users need WinRAR / 7-Zip / ZArchiver to extract |
| Search finds nothing for a known title | The site search is exact substring matching; try different variants — the 4-layer fallback covers Simplified/Traditional/Japanese writing, but ultra-rare single-character combos may still miss (see `_search_by_core_chars` in `jm_download.py`) |

## Project layout

```
jm_niang.py          # QQ bot main loop: OneBot WS client, command handling, uploads, pagination
jm_download.py       # jmcomic wrapper: download → AES ZIP, smart search (variants + pagination), cache, cleanup
test_jm_download.py  # offline unit tests
start_jmniang.bat    # optional Windows launcher
```

## License

MIT — see [LICENSE](LICENSE).
