#!/usr/bin/env python3
"""Send the watchdog's Telegram alert through the shared notifier (env TOKEN, CHAT, MESSAGE, URL)."""
import os
import sys

import notify


def main():
    try:
        notify.telegram_send(os.environ["TOKEN"], os.environ["CHAT"], f"{os.environ['MESSAGE']}. {os.environ['URL']}")
    except (notify.NotifyError, KeyError):
        print("alert-failed", file=sys.stderr)
        return 1
    print("alert-sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
