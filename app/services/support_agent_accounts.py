import argparse
from getpass import getpass

from app.services.demo_authorization import DemoAuthorizationService
from app.storage.json_store import DataStoreError, JsonRepository


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision an email/password account for a support agent."
    )
    parser.add_argument("--staff-id", required=True)
    parser.add_argument("--email", required=True)
    arguments = parser.parse_args()

    password = getpass("Password (12-256 characters): ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        parser.error("Passwords do not match.")

    service = DemoAuthorizationService(JsonRepository())
    try:
        service.create_support_agent_account(
            arguments.email,
            password,
            arguments.staff_id,
        )
    except (DataStoreError, ValueError) as exc:
        parser.error(str(exc))
    print("Support-agent account created.")


if __name__ == "__main__":
    main()
