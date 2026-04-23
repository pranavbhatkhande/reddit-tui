"""Entry point for reddit-tui."""
from reddit_tui.app import RedditTUI


def main() -> None:
    app = RedditTUI()
    app.run()


if __name__ == "__main__":
    main()
