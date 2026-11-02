import argparse
from getpass import getpass

from app.services.demo_authorization import DemoAuthorizationService
from app.storage.factory import repository_from_environment
from app.storage.json_store import DataStoreError


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision an email/password account for an existing customer."
    )
    parser.add_argument("--customer-id", required=True)
    parser.add_argument("--email", required=True)
    arguments = parser.parse_args()

    password = getpass("Password (12-256 characters): ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        parser.error("Passwords do not match.")

    service = DemoAuthorizationService(repository_from_environment())
    try:
        service.create_account(arguments.email, password, arguments.customer_id)
    except (DataStoreError, ValueError) as exc:
        parser.error(str(exc))
    print("Customer account created.")


if __name__ == "__main__":
    main()
