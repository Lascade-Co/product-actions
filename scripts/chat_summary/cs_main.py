#!/usr/bin/env python3
"""Daily SalesIQ chat digest for one product (port of chat-summary index.js).

  python3 cs_main.py <marine-radar|travel-animator> <build|send>

build renders the digest and freezes the Resend envelope; send posts it. The
workflow holds (scripts/common/hold.py) and dedupes (cs_editions.py dedupe)
between the two. See cs_pipeline for the environment.

Only fixed messages from trusted error classes reach stderr; anything else
(Google, HTTP or JSON errors can carry sheet IDs, credentials or chats) becomes
"Chat digest <command> failed; no delivery marker was recorded."
"""
import os
import sys

from claude_api import ClaudeError
import cs_pipeline
from cs_errors import DigestError
import cs_errors
from delivery import DeliveryError

COMMANDS = ("build", "send")
TRUSTED = (DigestError, DeliveryError, ClaudeError)


def failure_message(error, command):
    return cs_errors.failure_message(error, command, TRUSTED)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    products = cs_pipeline.PRODUCTS
    if len(args) != 2 or args[0] not in products or args[1] not in COMMANDS:
        print(f"Usage: cs_main.py <{'|'.join(sorted(products))}> <{'|'.join(COMMANDS)}>", file=sys.stderr)
        return 1
    product, command = products[args[0]], args[1]
    try:
        getattr(cs_pipeline, command)(product, env=os.environ)
        return 0
    except Exception as error:  # noqa: BLE001 - never print external error text
        print(failure_message(error, command), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
