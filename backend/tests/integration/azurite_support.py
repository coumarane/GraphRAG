"""Local Azurite settings. Production storage account names are refused."""

from __future__ import annotations

from pydantic import SecretStr

from graph_rag.config.settings import AzureBlobSettings

EMULATOR_ACCOUNT = "devstoreaccount1"
EMULATOR_KEY = (
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
)
_REFUSED = {"prod", "production", "prodaccount", "enterpriseprod"}


def local_azurite_settings(account: str = EMULATOR_ACCOUNT) -> AzureBlobSettings:
    """Return settings for the local emulator account and no other account."""
    normalized = account.strip().lower()
    if normalized in _REFUSED or "prod" in normalized:
        raise RuntimeError("Refusing a production storage account name")
    if normalized != EMULATOR_ACCOUNT:
        raise RuntimeError("Azurite tests only use the local emulator account")
    return AzureBlobSettings(
        account_name=EMULATOR_ACCOUNT,
        account_url=f"http://127.0.0.1:10000/{EMULATOR_ACCOUNT}",
        container="documents",
        access_key=SecretStr(EMULATOR_KEY),
    )
