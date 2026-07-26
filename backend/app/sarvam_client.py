"""Backend-only Sarvam credential and API integration boundary."""

import subprocess

KEYCHAIN_SERVICE = "sarvam-api"
KEYCHAIN_ACCOUNT = "vachan"
KEYCHAIN_TIMEOUT_SECONDS = 15


class SarvamCredentialError(RuntimeError):
    """Raised when the backend cannot securely load its Sarvam credential."""


def load_sarvam_api_key() -> str:
    """Load the Sarvam API key from macOS Keychain without exposing it."""
    command = (
        "security",
        "find-generic-password",
        "-s",
        KEYCHAIN_SERVICE,
        "-a",
        KEYCHAIN_ACCOUNT,
        "-w",
    )
    try:
        result = subprocess.run(  # noqa: S603
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=KEYCHAIN_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as error:
        raise SarvamCredentialError(
            "macOS Keychain CLI is unavailable; Vachan cannot load the Sarvam API key."
        ) from error
    except subprocess.TimeoutExpired as error:
        raise SarvamCredentialError(
            "Timed out while loading the Sarvam API key from macOS Keychain."
        ) from error
    except subprocess.CalledProcessError as error:
        raise SarvamCredentialError(
            "Sarvam API key is unavailable in macOS Keychain "
            f"(service={KEYCHAIN_SERVICE}, account={KEYCHAIN_ACCOUNT})."
        ) from error

    api_key = result.stdout.strip()
    if not api_key:
        raise SarvamCredentialError(
            "Sarvam API key entry exists but contains no value; refusing to start."
        )
    return api_key
