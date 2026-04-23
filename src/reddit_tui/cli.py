"""reddit-tui command-line interface.

Subcommands:
  (no args)    Launch the TUI (default)
  login        Interactively store Reddit credentials in the system keyring
  logout       Wipe stored credentials and cached token
  status       Print where credentials and token cache are loaded from
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from reddit_tui import auth


def _cmd_login(args: argparse.Namespace) -> int:
    try:
        import keyring  # noqa: F401
    except ImportError:
        print(
            "error: 'keyring' is not installed. install with:\n"
            "  pip install 'reddit-tui[keyring]'",
            file=sys.stderr,
        )
        return 2

    print("Reddit-TUI login — credentials are stored in the system keyring.")
    print("Create a 'script' app at https://www.reddit.com/prefs/apps to get")
    print("your client_id and client_secret.\n")

    client_id = input("client_id: ").strip()
    client_secret = getpass.getpass("client_secret: ").strip()
    username = input("reddit username: ").strip()
    password = getpass.getpass("reddit password: ")
    user_agent = input(
        f"user_agent (blank = default): "
    ).strip() or auth.DEFAULT_USER_AGENT

    if not all([client_id, client_secret, username, password]):
        print("error: all fields except user_agent are required", file=sys.stderr)
        return 1

    cfg = auth.AuthConfig(
        client_id=client_id,
        client_secret=client_secret,
        username=username,
        password=password,
        user_agent=user_agent,
    )

    print("\nverifying credentials with reddit…")
    try:
        token = asyncio.run(auth.fetch_token(cfg))
    except auth.AuthError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    auth.save_to_keyring(cfg)
    auth.save_token(token)
    print(f"✓ logged in as u/{username}; credentials stored in keyring")
    return 0


def _cmd_logout(_args: argparse.Namespace) -> int:
    auth.delete_from_keyring()
    if auth.TOKEN_PATH.exists():
        try:
            auth.TOKEN_PATH.unlink()
        except OSError:
            pass
    print("✓ credentials and cached token removed")
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    src = "none"
    try:
        kr = auth._try_keyring()
        if kr is not None:
            src = f"keyring (u/{kr.username})"
        elif auth.CONFIG_PATH.exists():
            src = f"config file: {auth.CONFIG_PATH}"
    except Exception as e:
        src = f"error: {e}"
    print(f"credentials: {src}")
    print(f"token cache: {auth.TOKEN_PATH} ({'present' if auth.TOKEN_PATH.exists() else 'absent'})")
    return 0


def _cmd_run(_args: argparse.Namespace) -> int:
    from reddit_tui.app import RedditTUI

    RedditTUI().run()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="reddit-tui", description="Terminal Reddit browser"
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("login", help="store Reddit credentials in the system keyring")
    sub.add_parser("logout", help="remove stored credentials and cached token")
    sub.add_parser("status", help="show where credentials are loaded from")
    sub.add_parser("run", help="launch the TUI (default)")

    args = parser.parse_args(argv)
    handler = {
        "login": _cmd_login,
        "logout": _cmd_logout,
        "status": _cmd_status,
        "run": _cmd_run,
        None: _cmd_run,
    }[args.cmd]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
