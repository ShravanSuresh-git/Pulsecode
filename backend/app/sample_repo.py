from __future__ import annotations

import shutil
from pathlib import Path

from git import Repo


def ensure_sample_repo() -> Path:
    root = Path("/tmp/pulsecode-sample-repo")
    if (root / ".git").exists():
        return root

    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    repo = Repo.init(root, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("user", "name", "PulseCode Demo")
        config.set_value("user", "email", "demo@pulsecode.local")

    _commit(repo, root, "start modular auth core", {
        "app/core/config.py": 'SETTINGS = {"region": "us"}\n',
        "app/auth/session.py": 'def create_session(user_id):\n    return {"user_id": user_id, "active": True}\n',
    })
    _commit(repo, root, "add billing module", {
        "app/billing/invoice.py": 'def create_invoice(account_id, amount):\n    return {"account_id": account_id, "amount": amount}\n',
    })
    _commit(repo, root, "connect billing visibility to auth", {
        "app/auth/permissions.py": 'def can_view_invoice(user, invoice):\n    return user.get("role") in {"admin", "billing"}\n',
        "app/billing/invoice.py": (
            "from app.auth.permissions import can_view_invoice\n\n"
            "def create_invoice(account_id, amount):\n"
            "    return {\"account_id\": account_id, \"amount\": amount}\n\n"
            "def visible_to(user, invoice):\n"
            "    return can_view_invoice(user, invoice)\n"
        ),
    })
    _commit(repo, root, "billing emits receipt notifications", {
        "app/notifications/email.py": 'def send_receipt(invoice):\n    return f"receipt:{invoice[\'account_id\']}"\n',
        "app/billing/invoice.py": (
            "from app.auth.permissions import can_view_invoice\n"
            "from app.notifications.email import send_receipt\n\n"
            "def create_invoice(account_id, amount):\n"
            "    invoice = {\"account_id\": account_id, \"amount\": amount}\n"
            "    send_receipt(invoice)\n"
            "    return invoice\n\n"
            "def visible_to(user, invoice):\n"
            "    return can_view_invoice(user, invoice)\n"
        ),
    })
    _commit(repo, root, "introduce reporting feedback loop", {
        "app/reporting/revenue.py": (
            "from app.billing.invoice import create_invoice\n\n"
            "def forecast(account_id):\n"
            "    return create_invoice(account_id, 100)[\"amount\"] * 12\n"
        ),
        "app/auth/session.py": (
            "from app.reporting.revenue import forecast\n\n"
            "def create_session(user_id):\n"
            "    return {\"user_id\": user_id, \"active\": True, \"forecast\": forecast(user_id)}\n"
        ),
    })
    _commit(repo, root, "refactor billing through event bus", {
        "app/core/events.py": "SUBSCRIBERS = []\n\n\ndef publish(event):\n    for subscriber in SUBSCRIBERS:\n        subscriber(event)\n",
        "app/billing/invoice.py": (
            "from app.auth.permissions import can_view_invoice\n"
            "from app.core.events import publish\n\n"
            "def create_invoice(account_id, amount):\n"
            "    invoice = {\"account_id\": account_id, \"amount\": amount}\n"
            "    publish({\"type\": \"invoice.created\", \"invoice\": invoice})\n"
            "    return invoice\n\n"
            "def visible_to(user, invoice):\n"
            "    return can_view_invoice(user, invoice)\n"
        ),
        "app/reporting/revenue.py": "def forecast(account_id):\n    return 1200\n",
    })
    _commit(repo, root, "add first architecture safety test", {
        "tests/test_flow.py": (
            "from app.billing.invoice import create_invoice\n\n"
            "def test_invoice():\n"
            "    assert create_invoice(\"acct\", 10)[\"amount\"] == 10\n"
        ),
    })
    _commit(repo, root, "decouple session and notifications", {
        "app/auth/session.py": 'def create_session(user_id):\n    return {"user_id": user_id, "active": True}\n',
        "app/notifications/email.py": (
            "from app.core.events import SUBSCRIBERS\n\n"
            "def on_event(event):\n"
            "    if event[\"type\"] == \"invoice.created\":\n"
            "        return f\"receipt:{event['invoice']['account_id']}\"\n\n"
            "SUBSCRIBERS.append(on_event)\n"
        ),
    })
    return root


def _commit(repo: Repo, root: Path, message: str, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        repo.index.add([str(path.relative_to(root))])
    repo.index.commit(message)
