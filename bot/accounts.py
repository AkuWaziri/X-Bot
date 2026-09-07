import json
from pathlib import Path


ACCOUNTS_FILE = Path(__file__).resolve().parent.parent / "config" / "monitored_accounts.json"


def load_accounts() -> list[str]:
    """Load enabled monitored X handles from the repository config."""
    if not ACCOUNTS_FILE.exists():
        return []

    with ACCOUNTS_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    accounts = data.get("accounts", [])
    return [normalize_handle(handle) for handle in accounts if normalize_handle(handle)]


def normalize_handle(handle: str) -> str:
    """Normalize an X handle to @username form."""
    handle = handle.strip()
    if handle.startswith("@"):
        handle = handle[1:]
    return f"@{handle}" if handle else ""


if __name__ == "__main__":
    print("Monitored accounts:")
    for handle in load_accounts():
        print(f"- {handle}")
