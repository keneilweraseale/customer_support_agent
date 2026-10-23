from datetime import datetime

from langchain_core.tools import StructuredTool

from app.services.cancellations import CancellationService
from app.storage.json_store import JsonRepository
from app.storage.models import (
    CancellationReasonCode,
    CancellationToolInput,
    ConfirmCancellationInput,
    OrderToolInput,
    ProductToolInput,
    ReviewSearchInput,
)

repository = JsonRepository()
cancellation_service = CancellationService(repository)


def _date(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _get_order_status(order_id: str, customer_id: str) -> dict[str, object]:
    order = repository.get_order(order_id)
    if order is None or order.customer_id != customer_id:
        return {"found": False, "message": "Order not found."}
    return {
        "found": True,
        "order_id": order.order_id,
        "order_status": order.order_status,
        "currency": order.currency,
        "created_at": _date(order.created_at),
        "updated_at": _date(order.updated_at),
    }


def _get_delivery_status(order_id: str, customer_id: str) -> dict[str, object]:
    order = repository.get_order(order_id)
    if order is None or order.customer_id != customer_id:
        return {"found": False, "message": "Order not found."}
    deliveries = repository.get_deliveries_for_order(order_id)
    return {
        "found": True,
        "order_id": order_id,
        "deliveries": [
            {
                "shipment_id": delivery.shipment_id,
                "carrier": delivery.carrier,
                "tracking_reference": delivery.tracking_reference,
                "delivery_status": delivery.delivery_status,
                "estimated_delivery": _date(delivery.estimated_delivery),
                "last_update": _date(delivery.last_update),
                "delay_reason": delivery.delay_reason,
            }
            for delivery in deliveries
        ],
    }


def _get_payment_status(order_id: str, customer_id: str) -> dict[str, object]:
    order = repository.get_order(order_id)
    if order is None or order.customer_id != customer_id:
        return {"found": False, "message": "Order not found."}
    payments = repository.get_payments_for_order(order_id)
    return {
        "found": True,
        "order_id": order_id,
        "payments": [
            {
                "payment_id": payment.payment_id,
                "payment_status": payment.payment_status,
                "error_code": payment.error_code,
                "updated_at": _date(payment.updated_at),
            }
            for payment in payments
        ],
    }


def _check_product_availability(product_id: str) -> dict[str, object]:
    product = repository.get_product(product_id)
    if product is None:
        return {"found": False, "message": "Product not found."}
    return {
        "found": True,
        "product_id": product.product_id,
        "name": product.name,
        "description": product.description,
        "available": product.stock_quantity > 0,
        "stock_quantity": product.stock_quantity,
        "price": product.price,
        "currency": product.currency,
        "warranty_summary": product.warranty_summary,
    }


def _search_customer_reviews(
    product_id: str | None = None,
    query: str | None = None,
) -> dict[str, object]:
    if product_id is not None and repository.get_product(product_id) is None:
        return {"found": False, "message": "Product not found.", "reviews": []}

    search_text = query.casefold() if query is not None else None
    reviews = [
        review
        for review in repository.get_reviews()
        if (product_id is None or review.product_id == product_id)
        and (
            search_text is None
            or search_text in review.review_text.casefold()
        )
    ]
    return {
        "found": bool(reviews),
        "reviews": [
            {
                "review_id": review.review_id,
                "product_id": review.product_id,
                "rating": review.rating,
                "review_text": review.review_text,
                "created_at": _date(review.created_at),
            }
            for review in reviews
        ],
    }


def _check_cancellation_eligibility(
    order_id: str,
    customer_id: str,
    reason_code: CancellationReasonCode = "not_provided",
    reason_text: str | None = None,
) -> dict[str, object]:
    return cancellation_service.check_eligibility(
        order_id,
        customer_id,
        reason_code,
        reason_text,
    )


def _cancel_order(
    order_id: str,
    customer_id: str,
    confirmation_token: str,
    idempotency_key: str | None = None,
    reason_code: CancellationReasonCode = "not_provided",
    reason_text: str | None = None,
) -> dict[str, object]:
    return cancellation_service.confirm_cancellation(
        order_id,
        customer_id,
        confirmation_token,
        idempotency_key,
        reason_code,
        reason_text,
    )


get_order_status_tool = StructuredTool.from_function(
    func=_get_order_status,
    name="get_order_status",
    description="Look up the status of an order owned by the supplied customer.",
    args_schema=OrderToolInput,
)
get_delivery_status_tool = StructuredTool.from_function(
    func=_get_delivery_status,
    name="get_delivery_status",
    description="Look up delivery updates for an order owned by the supplied customer.",
    args_schema=OrderToolInput,
)
get_payment_status_tool = StructuredTool.from_function(
    func=_get_payment_status,
    name="get_payment_status",
    description="Look up payment status for an order owned by the supplied customer.",
    args_schema=OrderToolInput,
)
check_product_availability_tool = StructuredTool.from_function(
    func=_check_product_availability,
    name="check_product_availability",
    description="Check current stock and price for a demo product.",
    args_schema=ProductToolInput,
)
search_customer_reviews_tool = StructuredTool.from_function(
    func=_search_customer_reviews,
    name="search_customer_reviews",
    description="Search demo reviews by product ID or text query.",
    args_schema=ReviewSearchInput,
)
check_cancellation_eligibility_tool = StructuredTool.from_function(
    func=_check_cancellation_eligibility,
    name="check_cancellation_eligibility",
    description="Check order cancellation eligibility and issue a short-lived confirmation token.",
    args_schema=CancellationToolInput,
)
cancel_order_tool = StructuredTool.from_function(
    func=_cancel_order,
    name="cancel_order",
    description="Cancel an eligible order after explicit confirmation using its server-issued token.",
    args_schema=ConfirmCancellationInput,
)

customer_support_tools: list[StructuredTool] = [
    get_order_status_tool,
    get_delivery_status_tool,
    get_payment_status_tool,
    check_product_availability_tool,
    search_customer_reviews_tool,
    check_cancellation_eligibility_tool,
    cancel_order_tool,
]
