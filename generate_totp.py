"""Generate a TOTP code from a secret.

SECURITY: The TOTP secret is a shared symmetric credential.  Passing it as a
command-line argument exposes it to every user on the host via the process
table (``ps aux``, ``/proc/<pid>/cmdline``) and in shell history.  The secret
is therefore read from, in priority order:

1. ``stdin`` (e.g. ``cat secret.txt | python generate_totp.py``)
2. The ``ATLAS_TOTP_SECRET`` environment variable
3. A command-line argument (DEPRECATED – prints a warning to stderr)
"""

import os
import sys

try:
    import pyotp
except ImportError:
    print("Please install pyotp: pip install pyotp")
    sys.exit(1)


def _read_secret_from_stdin() -> str | None:
    """Read the secret from stdin when data is piped in.

    Returns ``None`` when stdin is a TTY (interactive) or when no data is
    available, so the caller can fall back to other sources.
    """
    try:
        if not sys.stdin.isatty():
            data = sys.stdin.read().strip()
            if data:
                return data
    except (OSError, ValueError):
        # stdin is unavailable or closed – treat as no input
        pass
    return None


def get_secret() -> str | None:
    """Retrieve the TOTP secret from a secure source.

    Priority: stdin pipe -> ``ATLAS_TOTP_SECRET`` env var -> argv (deprecated).
    """
    # 1. stdin (most secure - never touches the process table)
    stdin_secret = _read_secret_from_stdin()
    if stdin_secret:
        return stdin_secret

    # 2. Environment variable
    env_secret = os.environ.get("ATLAS_TOTP_SECRET")
    if env_secret:
        return env_secret.strip()

    # 3. Command-line argument - DEPRECATED, leaks secret via ps/cmdline
    if len(sys.argv) > 1 and sys.argv[1] != "--generate-secret":
        sys.stderr.write(
            "WARNING: Passing the TOTP secret as a command-line argument is "
            "insecure (visible in the process table). "
            "Pipe it via stdin or set ATLAS_TOTP_SECRET instead.\n"
        )
        return sys.argv[1].replace(" ", "").upper()

    return None


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--generate-secret":
        # Using 64 characters (320 bits) which is highly secure and reliably supported by major authenticator apps
        print(pyotp.random_base32(length=64))
        sys.exit(0)

    secret = get_secret()
    if not secret:
        sys.stderr.write(
            "Usage: cat secret.txt | python generate_totp.py\n"
            "       ATLAS_TOTP_SECRET=<key> python generate_totp.py\n"
            "       python generate_totp.py --generate-secret\n"
        )
        sys.exit(1)

    # Normalise: the argv path already upper-cases; do the same for all sources
    # so behaviour stays consistent.
    secret = secret.replace(" ", "").upper()
    totp = pyotp.TOTP(secret)
    print(f"Your current TOTP code is: {totp.now()}")


if __name__ == "__main__":
    main()
