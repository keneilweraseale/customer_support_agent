from app.services.demo_authorization import provision_account_via_cli


def main() -> None:
    provision_account_via_cli(
        description="Provision an email/password account for an existing customer.",
        identifier_flag="customer-id",
        success_message="Customer account created.",
        create_account=lambda service, email, password, customer_id: service.create_account(
            email,
            password,
            customer_id,
        ),
    )


if __name__ == "__main__":
    main()
