from app.services.demo_authorization import provision_account_via_cli


def main() -> None:
    provision_account_via_cli(
        description="Provision an email/password account for a support agent.",
        identifier_flag="staff-id",
        success_message="Support-agent account created.",
        create_account=lambda service, email, password, staff_id: service.create_support_agent_account(
            email,
            password,
            staff_id,
        ),
    )


if __name__ == "__main__":
    main()
