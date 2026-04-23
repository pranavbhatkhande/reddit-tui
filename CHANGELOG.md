# Changelog

All notable changes to **reddit-tui** are documented here. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.3.0] — 2026-04-23

This is a substantial hardening release: the network layer is now async,
comment rendering scales to threads with hundreds of replies, credentials
can live in the system keyring, and there is a real test suite + CI.

### Added
- **Async HTTP** via `httpx.AsyncClient` throughout. Rate-limit headers
  are tracked and respected with cooperative throttling.
- **`MoreComments` placeholders** parsed from the comment tree. Press
  `M` on a focused "load more" line to fetch the missing replies via
  `/api/morechildren`.
- **Multi-line reply dialog** (`TextArea`-based). Submit with `ctrl+s`,
  cancel with `esc`. Markdown is supported.
- **Optional system-keyring credential storage** (`reddit-tui[keyring]`
  extra). Use `reddit-tui login` to interactively store your client_id /
  client_secret / username / password in the OS keyring.
- **CLI subcommands**:
  - `reddit-tui` / `reddit-tui run` — launch the TUI (default)
  - `reddit-tui login` — store credentials in the keyring
  - `reddit-tui logout` — wipe stored credentials and cached token
  - `reddit-tui status` — show where credentials are loaded from
- **Configurable `user_agent`** (per Reddit API guidelines).
- **`py.typed` marker** so downstream type-checkers see annotations.
- **Test suite** (42 tests) covering parsing, formatters, auth config,
  freshness logic, and CLI dispatch.
- **GitHub Actions CI**: pytest matrix on Python 3.10/3.11/3.12,
  ruff (required), mypy (advisory).
- `CHANGELOG.md` (this file).

### Changed
- **Auth-init no longer blocks app startup.** The TUI shows the
  subreddit screen immediately and verifies credentials in a worker;
  the title bar reflects sign-in progress.
- **Token refresh is coroutine-safe** (asyncio lock + double-checked
  cache); concurrent callers no longer trigger duplicate refreshes.
- **Unread inbox count** comes from `/api/v1/me`'s `inbox_count` instead
  of a heuristic over the inbox listing.
- **Comments are rendered into a single `Static` widget** using a Rich
  `Group`, replacing the per-comment widget approach. Threads with 500+
  comments now render and scroll smoothly.
- **CSS extracted** to `styles/{app,inbox,reply}.tcss` files instead of
  inline triple-quoted strings.
- **`Comment.replies`** widened from `List[Comment]` to
  `List[Comment | MoreComments]`.
- **`textual` dependency pinned to `>=8,<9`** (was unpinned).
- **Project metadata**: bumped to 0.3.0, requires Python 3.10+, declares
  `[project.optional-dependencies]` for `keyring` and `dev`.

### Fixed
- `clean_sub()` correctly normalizes `r/python`, `/r/python`,
  `r/python/`, whitespace, and empty input (returns `"all"`).
- Subreddit input no longer crashes on uppercase or wrapped slashes.
- App correctly closes the `httpx.AsyncClient` on exit.

### Removed
- `urllib`-based synchronous request path.
- `threading.Lock` token refresh; `@work(thread=True)` worker pattern.
- Inline `DEFAULT_CSS` blocks (moved to `.tcss` files).

[0.3.0]: https://github.com/anomalyco/reddit-tui/releases/tag/v0.3.0
