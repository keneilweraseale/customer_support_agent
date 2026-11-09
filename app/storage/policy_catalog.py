from datetime import datetime, timezone

from app.storage.models import PolicyDocument

PDF_POLICY_DOCUMENT = PolicyDocument(
    document_id="customer-support-policies",
    title="Customer Support AI Agent Policies",
    category="policies",
    source="policies/Policies.pdf",
    approved=True,
    updated_at=datetime(2026, 10, 23, 9, 15, 42, tzinfo=timezone.utc),
)
