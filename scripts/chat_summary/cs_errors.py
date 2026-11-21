"""Fixed, data-free diagnostics for chat-summary (port of src/errors.js)."""


class DigestError(Exception):
    """Only fixed messages authored by this application use this type."""


def failure_message(error, command, trusted=(DigestError,)):
    """A trusted error's own message, otherwise a generic line.

    External errors can carry requests, sheet IDs, model output or customer
    data, so never print their messages, causes or stacks.
    """
    if isinstance(error, trusted):
        return str(error)
    return f"Chat digest {command} failed; no delivery marker was recorded."
