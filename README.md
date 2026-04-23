# reddit-tui

A portable, terminal-based Reddit browser. No login required. No API keys.
Just clone and run.

Works on **Linux** and **macOS** with any Python 3.8+.

## Features

- Browse `r/popular` by default, or any subreddit you like
- Cycle sort: hot / new / top / rising
- View post body and full comment tree (with replies, indented)
- Search subreddits by name
- Open external links in your default browser
- Pure standard-library HTTP client (only one runtime dependency: `textual` for the TUI)
- **Optional logged-in mode** (script-app OAuth):
  - Subscribed-subreddits sidebar
  - Upvote / downvote posts and comments
  - Save / unsave posts and comments
  - Reply to posts and comments
  - Inbox view (replies + private messages)

## Install & Run

### Quick start (recommended)

```bash
git clone <this-repo> reddit-tui
cd reddit-tui
./reddit-tui
```

The launcher script will create a local `.venv/`, install dependencies, and start the app on first run. Subsequent runs reuse the venv and start instantly.

### Manual install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
reddit-tui
```

### Requirements

- Python 3.8 or newer
- Network access to `https://www.reddit.com`
- A terminal that supports modern ANSI / Unicode (most do)

## Keybindings

### Subreddit list view

| Key       | Action                       |
|-----------|------------------------------|
| `↑`/`↓`   | Move selection               |
| `Enter`   | Open post                    |
| `g`       | Go to a different subreddit  |
| `s`       | Cycle sort (hot/new/top/rising) |
| `/`       | Search subreddits            |
| `r`       | Refresh                      |
| `u` / `d` | Upvote / downvote (logged in) |
| `S`       | Save / unsave post (logged in) |
| `i`       | Open inbox (logged in)       |
| `q` / `Esc` | Back / Quit                |

### Post view

| Key       | Action                  |
|-----------|-------------------------|
| `j`/`k`   | Next / prev comment (or scroll) |
| `o`       | Open link in browser    |
| `r`       | Reload comments         |
| `u` / `d` | Upvote / downvote focused post or comment (logged in) |
| `S`       | Save / unsave focused post or comment (logged in) |
| `c`       | Reply to post (logged in) |
| `R`       | Reply to focused comment (logged in) |
| `q` / `Esc` | Back                  |

### Inbox view (logged in)

| Key       | Action                  |
|-----------|-------------------------|
| `j`/`k`   | Next / prev item        |
| `Enter`   | Open thread (for comment replies) |
| `m`       | Mark as read            |
| `r`       | Refresh                 |
| `q` / `Esc` | Back                  |

`Ctrl+C` quits from anywhere.

## Logging in (optional)

Logged-in mode uses Reddit's "script" app OAuth flow — designed for personal/single-user
use. Voting, commenting, saving, the subscribed-subs sidebar, and the inbox screen all
require logging in. **The app works fully without logging in**; everything below is optional.

### 1. Create a Reddit "script" app

1. Go to <https://www.reddit.com/prefs/apps>
2. Scroll down → **"create another app..."**
3. Pick **"script"**
4. Name: anything (e.g. `reddit-tui`)
5. Redirect URI: `http://localhost:8080` (unused, but required)
6. Click **create app**
7. Note the **client ID** (the string under the app name, looks like `aBcDeF12345`) and the **secret**.

### 2. Create the config file

Create `~/.config/reddit-tui/config.json` with:

```json
{
  "client_id": "your_client_id_here",
  "client_secret": "your_client_secret_here",
  "username": "your_reddit_username",
  "password": "your_reddit_password"
}
```

Restrict permissions:

```bash
chmod 600 ~/.config/reddit-tui/config.json
```

### 3. Run the app

```bash
./reddit-tui
```

You should see `logged in as u/<username>` in the title bar. Tokens are cached at
`~/.config/reddit-tui/auth.json` and refreshed automatically. If your password contains
special characters, JSON-escape them.

### Security notes

- The "script" app flow stores your password in plaintext on disk. This is acceptable
  only for personal use on a machine you control.
- The token cache file is created with mode `0600`.
- Reddit accounts with 2FA enabled cannot use the password grant. Use a non-2FA account
  or temporarily disable 2FA for the account you log in with.

## Project layout

```
reddit-tui/
├── reddit-tui              # portable launcher (bash)
├── requirements.txt
├── pyproject.toml
└── src/reddit_tui/
    ├── __main__.py
    ├── app.py              # Textual App
    ├── reddit_client.py    # stdlib-only Reddit JSON API client
    ├── utils.py
    └── screens/
        ├── subreddit_screen.py
        ├── post_screen.py
        └── input_dialog.py
```

## Notes

- This client uses Reddit's public JSON endpoints (e.g. `https://www.reddit.com/r/<sub>/hot.json`) when not logged in. When logged in via the script-app OAuth flow, it uses `https://oauth.reddit.com` with a bearer token.
- Reddit may rate-limit anonymous traffic. If you hit errors, wait a moment and press `r` to retry. OAuth traffic gets significantly higher rate limits.
