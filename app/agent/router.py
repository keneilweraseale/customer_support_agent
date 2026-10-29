import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from langchain_core.tools.base import ToolException

from app.rag.providers import ProviderConfigurationError
from app.rag.service import PolicyAnswer
from app.storage.json_store import DataStoreError

ORDER_ID_PATTERN = re.compile(r"\bORD-[A-Z0-9_-]+\b", re.IGNORECASE)
PRODUCT_ID_PATTERN = re.compile(r"\bPROD-[A-Z0-9_-]+\b", re.IGNORECASE)

ORDER_WORDS = ("order", "orders")
DELIVERY_WORDS = (
    "delivery",
    "deliver",
    "shipment",
    "tracking",
    "track",
    "parcel",
    "package",
)
PAYMENT_WORDS = ("payment", "paid", "charge", "charged", "transaction")
PRODUCT_WORDS = ("product", "stock", "availability", "available", "price", "in stock")
REVIEW_WORDS = ("review", "reviews", "rated", "rating")
POLICY_WORDS = (
    "policy",
    "refund",
    "return",
    "exchange",
    "shipping",
    "warranty",
    "contact",
    "how to order",
)
CANCEL_WORDS = ("cancel", "cancellation")
ARRIVAL_WORDS = ("arrive", "arrived", "late", "missing", "overdue", "hasn't come")
ESCALATION_WORDS = (
    "escalate",
    "support keeps ignoring",
    "ignored me",
    "human agent",
    "human support",
    "contact support",
    "contact a human",
    "speak to a human",
    "talk to a human",
    "real person",
)
ORDER_SEARCH_WORDS = (
    "find it",
    "find my order",
    "don't remember",
    "do not remember",
    "forgot my order",
    "no order number",
    "other order",
    "other one",
    "another one",
    "second one",
)
OTHER_ORDER_WORDS = (
    "the other one",
    "other one",
    "the other order",
    "other order",
    "another one",
    "second one",
)
CANCEL_ACTION_PATTERN = re.compile(
    r"\b(cancel|canceled|cancelled|canceling|cancelling)\b",
    re.IGNORECASE,
)


class ChatRoute(str, Enum):
    POLICY = "rag"
    ORDER = "order_tool"
    DELIVERY = "delivery_tool"
    PAYMENT = "payment_tool"
    PRODUCT = "product_tool"
    REVIEWS = "review_tool"
    MIXED = "rag_and_tool"
    MULTI = "multi_tool"
    CANCELLATION = "cancellation_check"
    CLARIFICATION = "clarification"
    BILLING_ISSUE = "billing_issue"
    CONVERSATION_MEMORY = "conversation_memory"
    OUT_OF_SCOPE = "out_of_scope"
    GREETING = "greeting"


class InvokableTool(Protocol):
    def invoke(self, input: dict[str, str]) -> dict[str, object]: ...


@dataclass(frozen=True)
class RouteDecision:
    route: ChatRoute
    order_id: str | None = None
    product_id: str | None = None
    subtasks: tuple[ChatRoute, ...] = ()


@dataclass(frozen=True)
class OrchestratedChatResult:
    answer: str
    route: ChatRoute
    sources: list[dict[str, str]]
    actions: list[dict[str, str]]
    needs_confirmation: bool = False
    long_term_record_created: bool = False
    needs_human_support: bool = False
    retrieval_context: list[str] | None = None
    actual_tool_calls: list[dict[str, object]] | None = None


class ChatOrchestrator:
    def __init__(
        self,
        *,
        order_tool: InvokableTool,
        delivery_tool: InvokableTool,
        payment_tool: InvokableTool,
        product_tool: InvokableTool,
        review_tool: InvokableTool,
        cancellation_tool: InvokableTool,
        policy_answer: Callable[[str], PolicyAnswer],
        customer_orders_tool: InvokableTool | None = None,
    ) -> None:
        self._order_tool = order_tool
        self._delivery_tool = delivery_tool
        self._payment_tool = payment_tool
        self._product_tool = product_tool
        self._review_tool = review_tool
        self._cancellation_tool = cancellation_tool
        self._policy_answer = policy_answer
        self._customer_orders_tool = customer_orders_tool

    def handle(
        self,
        message: str,
        customer_id: str | None = None,
        context_order_id: str | None = None,
        cancellation_preview_tool: InvokableTool | None = None,
    ) -> OrchestratedChatResult:
        actual_tool_calls: list[dict[str, object]] = []
        decision = classify_message(message)
        if (
            decision.route
            in {
                ChatRoute.ORDER,
                ChatRoute.DELIVERY,
                ChatRoute.PAYMENT,
                ChatRoute.CANCELLATION,
                ChatRoute.BILLING_ISSUE,
                ChatRoute.MULTI,
            }
            and decision.order_id is None
            and context_order_id is not None
            and not requests_order_search(message)
        ):
            decision = RouteDecision(
                decision.route,
                order_id=context_order_id,
                product_id=decision.product_id,
                subtasks=decision.subtasks,
            )
        if decision.route == ChatRoute.CLARIFICATION:
            return OrchestratedChatResult(
                answer=self._clarification(decision, message, customer_id),
                route=decision.route,
                sources=[],
                actions=[],
            )

        if decision.route == ChatRoute.OUT_OF_SCOPE:
            if _is_car_purchase_question(message):
                return OrchestratedChatResult(
                    answer=(
                        "For a car purchase, compare total ownership cost, safety, "
                        "reliability, fuel or charging needs, space, insurance, and "
                        "warranty coverage; then test-drive your shortlist. I "
                        "specialize in this store’s e-commerce support, but I’m "
                        "happy to help with products or orders here."
                    ),
                    route=decision.route,
                    sources=[],
                    actions=[],
                )
            return OrchestratedChatResult(
                answer=(
                    "Hi there! I’m here to help with this store’s orders, "
                    "deliveries, payments, returns, products, and policies. "
                    "I can’t answer general questions outside those topics, "
                    "but I’d be glad to help with a store-related question."
                ),
                route=decision.route,
                sources=[],
                actions=[],
            )

        if decision.route == ChatRoute.GREETING:
            return OrchestratedChatResult(
                answer=(
                    "Hi! I can help with orders, deliveries, payments, returns, "
                    "products, or store policies. What can I help you with?"
                ),
                route=decision.route,
                sources=[],
                actions=[],
            )

        if decision.route == ChatRoute.BILLING_ISSUE:
            if decision.order_id is None:
                return OrchestratedChatResult(
                    answer="I’m sorry you’re dealing with a payment issue. Please share the order reference so I can check the order and payment records before advising you.",
                    route=ChatRoute.CLARIFICATION,
                    sources=[],
                    actions=[],
                )
            if customer_id is None:
                return OrchestratedChatResult(
                    answer=(
                        "Please sign in before I look up private order and payment "
                        "information."
                    ),
                    route=decision.route,
                    sources=[],
                    actions=[],
                )
            return self._check_billing_issue(
                decision.order_id,
                customer_id,
                actual_tool_calls,
            )

        if decision.route == ChatRoute.MULTI:
            if decision.order_id is None:
                if ChatRoute.POLICY not in decision.subtasks:
                    return OrchestratedChatResult(
                        answer=(
                            "Hi! I can help check your order and delivery status. "
                            "Please provide the order reference so I can look it up."
                        ),
                        route=ChatRoute.CLARIFICATION,
                        sources=[],
                        actions=[],
                    )
            if customer_id is None:
                return OrchestratedChatResult(
                    answer="Please sign in before I look up private order information.",
                    route=ChatRoute.MULTI,
                    sources=[],
                    actions=[],
                )
            return self._handle_multiple_order_tasks(
                message,
                decision,
                customer_id,
                actual_tool_calls,
            )

        if decision.route == ChatRoute.POLICY:
            return self._answer_policy(message, actual_tool_calls)

        if decision.route == ChatRoute.MIXED:
            return self._answer_mixed(message, decision, actual_tool_calls)

        if decision.route in (
            ChatRoute.ORDER,
            ChatRoute.DELIVERY,
            ChatRoute.PAYMENT,
            ChatRoute.CANCELLATION,
        ):
            if (
                decision.order_id is None
                and customer_id is not None
                and self._customer_orders_tool is not None
                and requests_order_search(message)
            ):
                if decision.route == ChatRoute.DELIVERY:
                    return self._find_delivery_order(
                        message,
                        customer_id,
                        actual_tool_calls,
                        context_order_id if requests_other_order(message) else None,
                    )
                if (
                    decision.route in {ChatRoute.ORDER, ChatRoute.PAYMENT}
                    and requests_other_order(message)
                    and context_order_id is not None
                ):
                    return self._find_other_order(
                        decision.route,
                        customer_id,
                        context_order_id,
                        actual_tool_calls,
                    )
            if decision.order_id is None:
                return OrchestratedChatResult(
                    answer=(
                        "Please sign in and provide your order reference "
                        "(for example, ORD-1001)."
                        if customer_id is None
                        else "Please provide your order reference (for example, ORD-1001)."
                    ),
                    route=ChatRoute.CLARIFICATION,
                    sources=[],
                    actions=[],
                )
            if customer_id is None:
                return OrchestratedChatResult(
                    answer=(
                        "Please sign in before I look up private order information."
                    ),
                    route=decision.route,
                    sources=[],
                    actions=[],
                )
            if decision.route == ChatRoute.CANCELLATION:
                return self._check_cancellation(
                    decision.order_id,
                    customer_id,
                    actual_tool_calls,
                    cancellation_preview_tool,
                )

            tool, tool_name = {
                ChatRoute.ORDER: (self._order_tool, "get_order_status"),
                ChatRoute.DELIVERY: (self._delivery_tool, "get_delivery_status"),
                ChatRoute.PAYMENT: (self._payment_tool, "get_payment_status"),
            }[decision.route]
            result = self._invoke_tool(
                tool,
                {"order_id": decision.order_id, "customer_id": customer_id},
                tool_name,
                actual_tool_calls,
            )
            formatted = self._format_order_result(decision.route, result)
            if (
                decision.route == ChatRoute.PAYMENT
                and _is_refund_status_request(message)
            ):
                formatted = self._format_refund_status_result(
                    result,
                    decision.order_id,
                )
            elif (
                decision.route == ChatRoute.DELIVERY
                and _is_repeated_delivery_complaint(message)
            ):
                formatted = OrchestratedChatResult(
                    answer=(
                        "I’m sorry this has happened repeatedly; I understand "
                        f"why it’s frustrating. {formatted.answer}"
                    ),
                    route=formatted.route,
                    sources=formatted.sources,
                    actions=formatted.actions,
                    needs_human_support=formatted.needs_human_support,
                )
            if (
                decision.route == ChatRoute.DELIVERY
                and _requests_address_change(message)
            ):
                formatted = OrchestratedChatResult(
                    answer=(
                        f"{formatted.answer}\n\n"
                        "I can’t change a delivery address through this demo system. "
                        "I’m escalating the request so support can check whether "
                        "the address can still be updated."
                    ),
                    route=formatted.route,
                    sources=formatted.sources,
                    actions=formatted.actions,
                    needs_human_support=True,
                )
            return self._with_tool_calls(formatted, actual_tool_calls)

        if decision.route == ChatRoute.PRODUCT:
            if decision.product_id is None:
                return OrchestratedChatResult(
                    answer="Please provide the product reference (for example, PROD-001).",
                    route=ChatRoute.CLARIFICATION,
                    sources=[],
                    actions=[],
                )
            result = self._invoke_tool(
                self._product_tool,
                {"product_id": decision.product_id},
                "check_product_availability",
                actual_tool_calls,
            )
            return self._with_tool_calls(
                self._format_product_result(result),
                actual_tool_calls,
            )

        if decision.route == ChatRoute.REVIEWS:
            product_id = decision.product_id
            query = None if product_id else message
            tool_input = {"product_id": product_id} if product_id else {"query": query}
            result = self._invoke_tool(
                self._review_tool,
                tool_input,
                "search_customer_reviews",
                actual_tool_calls,
            )
            return self._with_tool_calls(
                self._format_review_result(result),
                actual_tool_calls,
            )

        return OrchestratedChatResult(
            answer="I couldn’t determine what information you need. Could you clarify your question?",
            route=ChatRoute.CLARIFICATION,
            sources=[],
            actions=[],
        )

    def _format_refund_status_result(
        self,
        result: dict[str, object],
        order_id: str,
    ) -> OrchestratedChatResult:
        if result.get("unavailable") is True:
            answer = (
                "I couldn’t access the payment record, so I can’t verify whether "
                "a refund was processed. Please try again later or send this "
                "request to support."
            )
            needs_human_support = True
        else:
            payments = result.get("payments")
            valid_payments = (
                payments
                if isinstance(payments, list)
                and payments
                and all(
                    isinstance(item, dict)
                    and isinstance(item.get("payment_id"), str)
                    and isinstance(item.get("payment_status"), str)
                    for item in payments
                )
                else None
            )
            if result.get("found") is not True or valid_payments is None:
                answer = (
                    f"I couldn’t verify the payment or refund record for order "
                    f"{order_id}. Please check the order reference or contact "
                    "support for help."
                )
                needs_human_support = True
            elif all(
                item["payment_status"] == "refunded"
                for item in valid_payments
            ):
                answer = (
                    f"The payment records for order {order_id} show the payment "
                    "as refunded."
                )
                needs_human_support = False
            else:
                payment_summary = "; ".join(
                    f"{item['payment_id']} is recorded as {item['payment_status']}"
                    for item in valid_payments
                )
                answer = (
                    f"I checked order {order_id}; its payment record shows "
                    f"{payment_summary}. This system has no separate refund "
                    "record, so I can’t confirm that a refund was processed. "
                    "I can send this to support for review."
                )
                needs_human_support = True
        return OrchestratedChatResult(
            answer=answer,
            route=ChatRoute.PAYMENT,
            sources=[],
            actions=[],
            needs_human_support=needs_human_support,
        )

    def _handle_multiple_order_tasks(
        self,
        message: str,
        decision: RouteDecision,
        customer_id: str,
        actual_tool_calls: list[dict[str, object]],
    ) -> OrchestratedChatResult:
        tools = {
            ChatRoute.ORDER: (self._order_tool, "get_order_status"),
            ChatRoute.DELIVERY: (self._delivery_tool, "get_delivery_status"),
            ChatRoute.PAYMENT: (self._payment_tool, "get_payment_status"),
        }
        answers: list[str] = []
        sources: list[dict[str, str]] = []
        needs_human_support = False
        for route in decision.subtasks:
            if route == ChatRoute.POLICY:
                policy_result = self._answer_policy(message, actual_tool_calls)
                answers.append(f"Policy: {policy_result.answer}")
                sources.extend(policy_result.sources)
                needs_human_support = (
                    needs_human_support or policy_result.needs_human_support
                )
                continue
            if decision.order_id is None:
                if route == ChatRoute.DELIVERY and _is_repeated_delivery_complaint(message):
                    answers.append(
                        "Delivery: I’m sorry this has happened repeatedly; I "
                        "understand why it’s frustrating. Please provide the "
                        "order reference so I can check the latest update."
                    )
                else:
                    answers.append(
                        f"{_route_label(route)}: Please provide your order "
                        "reference so I can check this."
                    )
                continue
            tool, tool_name = tools[route]
            result = self._invoke_tool(
                tool,
                {
                    "order_id": decision.order_id or "",
                    "customer_id": customer_id,
                },
                tool_name,
                actual_tool_calls,
            )
            formatted = self._format_order_result(route, result)
            empathy = (
                "I’m sorry this has happened repeatedly; I understand why it’s "
                "frustrating. "
                if route == ChatRoute.DELIVERY
                and _is_repeated_delivery_complaint(message)
                else ""
            )
            answers.append(f"{_route_label(route)}: {empathy}{formatted.answer}")
            needs_human_support = (
                needs_human_support or result.get("unavailable") is True
            )

        if _requests_address_change(message):
            answers.append(
                "Address change: I can’t change a delivery address through this "
                "demo system. I’m escalating the request so support can check "
                "whether it can still be updated."
            )
            needs_human_support = True
        return OrchestratedChatResult(
            answer="\n".join(answers),
            route=ChatRoute.MULTI,
            sources=sources,
            actions=[],
            needs_human_support=needs_human_support,
            actual_tool_calls=list(actual_tool_calls),
        )

    def _answer_policy(
        self,
        message: str,
        actual_tool_calls: list[dict[str, object]],
    ) -> OrchestratedChatResult:
        try:
            result = self._policy_answer(message)
        except ProviderConfigurationError:
            return OrchestratedChatResult(
                answer="Approved policy answers are temporarily unavailable. Please contact support.",
                route=ChatRoute.POLICY,
                sources=[],
                actions=[],
                needs_human_support=True,
                retrieval_context=[],
                actual_tool_calls=list(actual_tool_calls),
            )
        return OrchestratedChatResult(
            answer=result.answer,
            route=ChatRoute.POLICY,
            sources=result.sources,
            actions=[],
            needs_human_support=getattr(result, "needs_human_support", False),
            retrieval_context=[
                retrieved.chunk.text for retrieved in result.retrieval.results
            ],
            actual_tool_calls=list(actual_tool_calls),
        )

    def _answer_mixed(
        self,
        message: str,
        decision: RouteDecision,
        actual_tool_calls: list[dict[str, object]],
    ) -> OrchestratedChatResult:
        tool_result = self._invoke_tool(
            self._product_tool,
            {"product_id": decision.product_id or ""},
            "check_product_availability",
            actual_tool_calls,
        )
        product_answer = self._format_product_result(tool_result)
        try:
            policy_result = self._policy_answer(message)
        except ProviderConfigurationError:
            return OrchestratedChatResult(
                answer=(
                    f"{product_answer.answer}\n\n"
                    "I couldn’t check the approved policy information right now. "
                    "Please contact support for that part."
                ),
                route=ChatRoute.MIXED,
                sources=[],
                actions=[],
                needs_human_support=True,
                retrieval_context=[],
                actual_tool_calls=list(actual_tool_calls),
            )
        return OrchestratedChatResult(
            answer=(
                f"Policy information: {policy_result.answer}\n\n"
                f"Current product information: {product_answer.answer}"
            ),
            route=ChatRoute.MIXED,
            sources=policy_result.sources,
            actions=[],
            needs_human_support=getattr(policy_result, "needs_human_support", False),
            retrieval_context=[
                retrieved.chunk.text for retrieved in policy_result.retrieval.results
            ],
            actual_tool_calls=list(actual_tool_calls),
        )

    def _check_cancellation(
        self,
        order_id: str,
        customer_id: str,
        actual_tool_calls: list[dict[str, object]],
        cancellation_preview_tool: InvokableTool | None = None,
    ) -> OrchestratedChatResult:
        result = self._invoke_tool(
            cancellation_preview_tool or self._cancellation_tool,
            {"order_id": order_id, "customer_id": customer_id},
            "check_cancellation_eligibility",
            actual_tool_calls,
        )
        if result.get("found") is not True:
            return OrchestratedChatResult(
                answer="I couldn’t find that order for this demo customer.",
                route=ChatRoute.CANCELLATION,
                sources=[],
                actions=[],
                retrieval_context=[],
                actual_tool_calls=list(actual_tool_calls),
            )
        if result.get("eligible") is not True:
            return OrchestratedChatResult(
                answer="This order is not eligible for cancellation.",
                route=ChatRoute.CANCELLATION,
                sources=[],
                actions=[],
                retrieval_context=[],
                actual_tool_calls=list(actual_tool_calls),
                long_term_record_created=True,
            )
        token = result.get("confirmation_token")
        if not isinstance(token, str):
            return OrchestratedChatResult(
                answer="I couldn’t prepare a safe cancellation confirmation. No change was made.",
                route=ChatRoute.CANCELLATION,
                sources=[],
                actions=[],
                retrieval_context=[],
                actual_tool_calls=list(actual_tool_calls),
                long_term_record_created=True,
            )
        return OrchestratedChatResult(
            answer=(
                f"Order {order_id} appears eligible for cancellation. "
                "Please explicitly confirm before any change is made."
            ),
            route=ChatRoute.CANCELLATION,
            sources=[],
            actions=[
                {
                    "type": "confirm_cancellation",
                    "order_id": order_id,
                    "confirmation_token": token,
                }
            ],
            needs_confirmation=True,
            long_term_record_created=True,
            retrieval_context=[],
            actual_tool_calls=list(actual_tool_calls),
        )

    def _check_billing_issue(
        self,
        order_id: str,
        customer_id: str,
        actual_tool_calls: list[dict[str, object]],
    ) -> OrchestratedChatResult:
        order_result = self._invoke_tool(
            self._order_tool,
            {"order_id": order_id, "customer_id": customer_id},
            "get_order_status",
            actual_tool_calls,
        )
        payment_result = self._invoke_tool(
            self._payment_tool,
            {"order_id": order_id, "customer_id": customer_id},
            "get_payment_status",
            actual_tool_calls,
        )
        def finish(result: OrchestratedChatResult) -> OrchestratedChatResult:
            return self._with_tool_calls(result, actual_tool_calls)

        if order_result.get("unavailable") is True:
            return finish(OrchestratedChatResult(
                answer=(
                    f"I couldn’t access the order record for {order_id}, so I "
                    "couldn’t verify its cancellation or payment. I’m escalating "
                    "this so the team can check the charge and refund status."
                ),
                route=ChatRoute.BILLING_ISSUE,
                sources=[],
                actions=[],
                needs_human_support=True,
            ))
        if payment_result.get("unavailable") is True:
            return finish(OrchestratedChatResult(
                answer=(
                    f"I checked order {order_id}, but couldn’t access its payment "
                    "record. I’m escalating this so the team can check the charge "
                    "and refund status."
                ),
                route=ChatRoute.BILLING_ISSUE,
                sources=[],
                actions=[],
                needs_human_support=True,
            ))
        if order_result.get("found") is not True:
            return finish(OrchestratedChatResult(
                answer=(
                    f"I couldn’t find order {order_id} for this verified demo "
                    "customer, so I couldn’t check its payment."
                ),
                route=ChatRoute.BILLING_ISSUE,
                sources=[],
                actions=[],
                needs_human_support=True,
            ))
        order_status = order_result.get("order_status")
        payments = payment_result.get("payments")
        if (
            not isinstance(order_status, str)
            or payment_result.get("found") is not True
            or not isinstance(payments, list)
            or not payments
            or not all(
                isinstance(item, dict)
                and isinstance(item.get("payment_id"), str)
                and isinstance(item.get("payment_status"), str)
                for item in payments
            )
        ):
            return finish(OrchestratedChatResult(
                answer=(
                    f"I found order {order_id}, but couldn’t verify both its "
                    "order and payment records. I’m escalating this so the team "
                    "can investigate the charge and refund status."
                ),
                route=ChatRoute.BILLING_ISSUE,
                sources=[],
                actions=[],
                needs_human_support=True,
            ))

        payment_summary = "; ".join(
            f"payment {item['payment_id']} is recorded as {item['payment_status']}"
            + (
                f" (updated {item['updated_at'][:10]})"
                if isinstance(item.get("updated_at"), str)
                else ""
            )
            for item in payments
        )
        if order_status == "cancelled" and any(
            item["payment_status"] == "paid" for item in payments
        ):
            order_updated_at = order_result.get("updated_at")
            order_update = (
                f" (order record last updated {order_updated_at[:10]})"
                if isinstance(order_updated_at, str)
                else ""
            )
            answer = (
                f"I checked order {order_id}: it is marked cancelled{order_update}, while "
                f"{payment_summary}. Those records need to be reconciled; I "
                "can’t issue a refund directly, so I’m escalating this for the "
                "team to investigate the charge and refund."
            )
        else:
            answer = (
                f"I checked order {order_id}: it is marked {order_status}, and "
                f"{payment_summary}. I can’t issue a refund directly, so I’m "
                "escalating your refund request for review."
            )
        return finish(OrchestratedChatResult(
            answer=answer,
            route=ChatRoute.BILLING_ISSUE,
            sources=[],
            actions=[],
            needs_human_support=True,
        ))

    def _find_delivery_order(
        self,
        message: str,
        customer_id: str,
        actual_tool_calls: list[dict[str, object]],
        exclude_order_id: str | None = None,
    ) -> OrchestratedChatResult:
        if self._customer_orders_tool is None:
            raise RuntimeError("Customer order search tool is not configured.")
        result = self._invoke_tool(
            self._customer_orders_tool,
            {"customer_id": customer_id},
            "find_customer_orders",
            actual_tool_calls,
        )
        orders = result.get("orders")
        if not isinstance(orders, list):
            return self._with_tool_calls(OrchestratedChatResult(
                answer=(
                    "I couldn’t access your order list just now. I’m escalating "
                    "your delivery concern; if you contact support, sharing the "
                    "approximate order date or item will help them locate it."
                ),
                route=ChatRoute.DELIVERY,
                sources=[],
                actions=[],
                needs_human_support=True,
            ), actual_tool_calls)
        candidates = [
            item
            for item in orders
            if isinstance(item, dict)
            and isinstance(item.get("order_id"), str)
            and (
                exclude_order_id is not None
                or item.get("order_status") in {"processing", "shipped"}
            )
            and item.get("order_id") != exclude_order_id
        ]
        if len(candidates) != 1:
            if candidates:
                references = ", ".join(item["order_id"] for item in candidates)
                answer = (
                    f"I found more than one active order ({references}), so I "
                    "can’t safely choose which delivery you mean. Please tell "
                    "me the item or approximate order date."
                )
            else:
                answer = (
                    "I couldn’t identify an active, undelivered order in this "
                    "verified demo account. Please share the item or approximate "
                    "order date so I can narrow it down."
                )
            return self._with_tool_calls(OrchestratedChatResult(
                answer=answer,
                route=ChatRoute.DELIVERY,
                sources=[],
                actions=[],
                needs_human_support=has_any(message.casefold(), ESCALATION_WORDS),
            ), actual_tool_calls)

        order_id = candidates[0]["order_id"]
        delivery_result = self._invoke_tool(
            self._delivery_tool,
            {"order_id": order_id, "customer_id": customer_id},
            "get_delivery_status",
            actual_tool_calls,
        )
        answer = self._format_order_result(ChatRoute.DELIVERY, delivery_result).answer
        should_escalate = has_any(message.casefold(), ESCALATION_WORDS)
        if should_escalate:
            answer = (
                f"I found order {order_id} in your verified demo account. "
                f"{answer} Since you asked for escalation, I’m sending this "
                "delivery concern to the support team."
            )
        return self._with_tool_calls(OrchestratedChatResult(
            answer=answer,
            route=ChatRoute.DELIVERY,
            sources=[],
            actions=[],
            needs_human_support=should_escalate,
        ), actual_tool_calls)

    def _find_other_order(
        self,
        route: ChatRoute,
        customer_id: str,
        current_order_id: str,
        actual_tool_calls: list[dict[str, object]],
    ) -> OrchestratedChatResult:
        if self._customer_orders_tool is None:
            raise RuntimeError("Customer order search tool is not configured.")
        result = self._invoke_tool(
            self._customer_orders_tool,
            {"customer_id": customer_id},
            "find_customer_orders",
            actual_tool_calls,
        )
        orders = result.get("orders")
        candidates = [
            item
            for item in orders
            if isinstance(item, dict)
            and isinstance(item.get("order_id"), str)
            and item["order_id"] != current_order_id
        ] if isinstance(orders, list) else []
        if len(candidates) != 1:
            answer = (
                "I couldn’t access your other orders just now. Please share the "
                "order reference so I can check it."
                if result.get("unavailable") is True
                else "I couldn’t safely identify a single other order. Please "
                "tell me which order reference you mean."
            )
            return self._with_tool_calls(OrchestratedChatResult(
                answer=answer,
                route=ChatRoute.CLARIFICATION,
                sources=[],
                actions=[],
                needs_human_support=result.get("unavailable") is True,
            ), actual_tool_calls)

        order_id = candidates[0]["order_id"]
        tool, tool_name = {
            ChatRoute.ORDER: (self._order_tool, "get_order_status"),
            ChatRoute.PAYMENT: (self._payment_tool, "get_payment_status"),
        }[route]
        order_result = self._invoke_tool(
            tool,
            {"order_id": order_id, "customer_id": customer_id},
            tool_name,
            actual_tool_calls,
        )
        return self._with_tool_calls(
            self._format_order_result(route, order_result),
            actual_tool_calls,
        )

    def _invoke_tool(
        self,
        tool: InvokableTool,
        tool_input: dict[str, str],
        tool_name: str,
        actual_tool_calls: list[dict[str, object]],
    ) -> dict[str, object]:
        try:
            result = tool.invoke(tool_input)
        except (DataStoreError, ToolException):
            actual_tool_calls.append(
                self._tool_trace(tool_name, tool_input, {"unavailable": True})
            )
            return {"found": False, "unavailable": True}
        if not isinstance(result, dict):
            actual_tool_calls.append(
                self._tool_trace(tool_name, tool_input, {"unavailable": True})
            )
            return {"found": False, "unavailable": True}
        actual_tool_calls.append(self._tool_trace(tool_name, tool_input, result))
        return result

    def _tool_trace(
        self,
        tool_name: str,
        tool_input: dict[str, str],
        result: dict[str, object],
    ) -> dict[str, object]:
        safe_arguments = {
            key: value if key in {"order_id", "product_id"} else "[redacted]"
            for key, value in tool_input.items()
        }
        if result.get("unavailable") is True:
            result_status = "unavailable"
        elif isinstance(result.get("eligible"), bool):
            result_status = "eligible" if result["eligible"] else "ineligible"
        elif isinstance(result.get("cancelled"), bool):
            result_status = "cancelled" if result["cancelled"] else "not_cancelled"
        elif result.get("found") is False:
            result_status = "not_found"
        else:
            result_status = "success"
        return {
            "name": tool_name,
            "arguments": safe_arguments,
            "result_status": result_status,
        }

    def _with_tool_calls(
        self,
        result: OrchestratedChatResult,
        actual_tool_calls: list[dict[str, object]],
    ) -> OrchestratedChatResult:
        return OrchestratedChatResult(
            answer=result.answer,
            route=result.route,
            sources=result.sources,
            actions=result.actions,
            needs_confirmation=result.needs_confirmation,
            long_term_record_created=result.long_term_record_created,
            needs_human_support=result.needs_human_support,
            retrieval_context=result.retrieval_context,
            actual_tool_calls=list(actual_tool_calls),
        )

    def _format_order_result(
        self,
        route: ChatRoute,
        result: dict[str, object],
    ) -> OrchestratedChatResult:
        if result.get("unavailable") is True:
            answer = {
                ChatRoute.ORDER: "Order information is temporarily unavailable. Please try again later.",
                ChatRoute.DELIVERY: "Delivery information is temporarily unavailable. Please try again later.",
                ChatRoute.PAYMENT: "Payment information is temporarily unavailable. Please try again later.",
            }[route]
        elif result.get("found") is not True:
            answer = "I couldn’t find that order for this demo customer."
        elif route == ChatRoute.ORDER:
            order_id = result.get("order_id")
            status = result.get("order_status")
            answer = (
                f"Order {order_id} is currently {status}."
                if isinstance(order_id, str) and isinstance(status, str)
                else "Order information is temporarily unavailable. Please try again later."
            )
        elif route == ChatRoute.DELIVERY:
            deliveries = result.get("deliveries")
            if not isinstance(deliveries, list) or not deliveries or not all(
                isinstance(item, dict)
                and isinstance(item.get("shipment_id"), str)
                and isinstance(item.get("delivery_status"), str)
                for item in deliveries
            ):
                answer = "I couldn’t find delivery updates for that order."
            else:
                delivery_summary = "; ".join(
                    f"Shipment {item['shipment_id']} is {item['delivery_status']}"
                    + (
                        f", estimated for {item['estimated_delivery']}."
                        if item.get("estimated_delivery")
                        else "."
                    )
                    + (
                        f" Delay reason: {item['delay_reason']}."
                        if isinstance(item.get("delay_reason"), str)
                        else ""
                    )
                    for item in deliveries
                )
                order_id = result.get("order_id")
                answer = (
                    f"For order {order_id}: {delivery_summary}"
                    if isinstance(order_id, str)
                    else delivery_summary
                )
        else:
            payments = result.get("payments")
            if not isinstance(payments, list) or not payments or not all(
                isinstance(item, dict)
                and isinstance(item.get("payment_id"), str)
                and isinstance(item.get("payment_status"), str)
                for item in payments
            ):
                answer = "I couldn’t find payment information for that order."
            else:
                payment_summary = "; ".join(
                    f"Payment {item['payment_id']} is {item['payment_status']}"
                    + (f" (code: {item['error_code']})" if item.get("error_code") else "")
                    for item in payments
                )
                order_id = result.get("order_id")
                answer = (
                    f"For order {order_id}: {payment_summary}"
                    if isinstance(order_id, str)
                    else payment_summary
                )
        return OrchestratedChatResult(
            answer=answer,
            route=route,
            sources=[],
            actions=[],
        )

    def _format_product_result(self, result: dict[str, object]) -> OrchestratedChatResult:
        if result.get("unavailable") is True:
            answer = "Product information is temporarily unavailable. Please try again later."
        elif result.get("found") is not True:
            answer = "I couldn’t find that product in the demo catalogue."
        elif (
            not isinstance(result.get("name"), str)
            or not isinstance(result.get("available"), bool)
            or not isinstance(result.get("stock_quantity"), int)
            or isinstance(result.get("stock_quantity"), bool)
            or not isinstance(result.get("price"), (int, float))
            or not isinstance(result.get("currency"), str)
        ):
            answer = "Product information is temporarily unavailable. Please try again later."
        else:
            availability = "in stock" if result.get("available") else "out of stock"
            answer = (
                f"{result['name']} is {availability} "
                f"({result['stock_quantity']} available) at "
                f"{result['price']} {result['currency']}."
            )
            if result.get("description"):
                answer += f" {result['description']}"
            if result.get("warranty_summary"):
                answer += f" Warranty: {result['warranty_summary']}"
        return OrchestratedChatResult(
            answer=answer,
            route=ChatRoute.PRODUCT,
            sources=[],
            actions=[],
        )

    def _format_review_result(self, result: dict[str, object]) -> OrchestratedChatResult:
        if result.get("unavailable") is True:
            answer = "Review information is temporarily unavailable. Please try again later."
            return OrchestratedChatResult(
                answer=answer,
                route=ChatRoute.REVIEWS,
                sources=[],
                actions=[],
            )
        reviews = result.get("reviews")
        if result.get("found") is not True or not isinstance(reviews, list) or not reviews:
            answer = "I couldn’t find matching demo reviews."
        elif not all(
            isinstance(item, dict)
            and isinstance(item.get("rating"), int)
            and isinstance(item.get("review_text"), str)
            for item in reviews
        ):
            answer = "Review information is temporarily unavailable. Please try again later."
        else:
            answer = "; ".join(
                f"{item['rating']}/5: {item['review_text']}"
                for item in reviews
            )
        return OrchestratedChatResult(
            answer=answer,
            route=ChatRoute.REVIEWS,
            sources=[],
            actions=[],
        )

    def _clarification(
        self,
        decision: RouteDecision,
        message: str,
        customer_id: str | None,
    ) -> str:
        if has_any(message, PRODUCT_WORDS) and has_any(message, POLICY_WORDS):
            return (
                "Please provide a product reference (for example, PROD-001) so I can "
                "check current product information alongside the approved policy."
            )
        if has_any(message, CANCEL_WORDS) and decision.order_id is None:
            return "Which order would you like to check for cancellation? Please provide its order reference."
        if has_any(message, DELIVERY_WORDS + PAYMENT_WORDS + ORDER_WORDS):
            if customer_id is None:
                answer = "Please sign in and provide your order reference so I can look up private order information."
            else:
                answer = "Please provide your order reference (for example, ORD-1001)."
            if _is_repeated_delivery_complaint(message):
                return (
                    "I’m sorry this has happened repeatedly; I understand why "
                    f"it’s frustrating. {answer}"
                )
            return answer
        if has_any(message, PRODUCT_WORDS) and decision.product_id is None:
            return "Please provide the product reference (for example, PROD-001)."
        return "I couldn’t determine what information you need. Could you clarify your question?"


def classify_message(message: str) -> RouteDecision:
    normalized = message.casefold()
    order_ids = {
        order_id.upper() for order_id in ORDER_ID_PATTERN.findall(message)
    }
    if len(order_ids) > 1:
        return RouteDecision(ChatRoute.CLARIFICATION)
    order_id = next(iter(order_ids), None)
    product_match = PRODUCT_ID_PATTERN.search(message)
    product_id = product_match.group(0).upper() if product_match else None
    has_order_intent = has_any(normalized, ORDER_WORDS)
    has_delivery_intent = has_any(normalized, DELIVERY_WORDS)
    has_payment_intent = has_any(normalized, PAYMENT_WORDS)
    has_product_intent = has_any(normalized, PRODUCT_WORDS)
    has_review_intent = has_any(normalized, REVIEW_WORDS)
    has_policy_intent = has_any(normalized, POLICY_WORDS)
    has_cancellation_intent = has_any(normalized, CANCEL_WORDS)
    is_how_to_request = re.search(r"\bhow\s+(do|can|should)\s+i\b", normalized) is not None

    is_billing_issue = (
        has_cancellation_intent
        and (
            has_payment_intent
            or (
                has_any(normalized, ("refund", "money back", "bank account"))
                and has_any(normalized, ("want", "get", "charged", "paid", "back"))
            )
        )
        and not (has_policy_intent and not has_payment_intent)
    )
    if is_billing_issue:
        return RouteDecision(ChatRoute.BILLING_ISSUE, order_id, product_id)

    if has_cancellation_intent and is_how_to_request:
        return RouteDecision(ChatRoute.POLICY, order_id, product_id)

    if has_cancellation_intent:
        if (
            CANCEL_ACTION_PATTERN.search(message)
            and not is_how_to_request
        ) or not has_policy_intent:
            return RouteDecision(ChatRoute.CANCELLATION, order_id, product_id)

    if _is_refund_status_request(normalized):
        return RouteDecision(ChatRoute.PAYMENT, order_id, product_id)

    if has_product_intent and has_policy_intent and not product_id:
        return RouteDecision(ChatRoute.CLARIFICATION, order_id, product_id)

    if has_product_intent and has_policy_intent and product_id:
        return RouteDecision(ChatRoute.MIXED, order_id, product_id)

    order_tasks: list[ChatRoute] = []
    if (
        has_order_intent
        and not requests_order_search(message)
        and not requests_other_order(message)
    ):
        order_tasks.append(ChatRoute.ORDER)
    if has_delivery_intent or has_any(normalized, ARRIVAL_WORDS):
        order_tasks.append(ChatRoute.DELIVERY)
    if has_payment_intent:
        order_tasks.append(ChatRoute.PAYMENT)
    if has_policy_intent and order_tasks:
        order_tasks.append(ChatRoute.POLICY)
    if len(order_tasks) > 1:
        return RouteDecision(
            ChatRoute.MULTI,
            order_id,
            product_id,
            tuple(order_tasks),
        )

    if has_payment_intent:
        return RouteDecision(ChatRoute.PAYMENT, order_id, product_id)
    if has_delivery_intent:
        return RouteDecision(ChatRoute.DELIVERY, order_id, product_id)
    if has_any(normalized, ARRIVAL_WORDS):
        return RouteDecision(ChatRoute.DELIVERY, order_id, product_id)
    if has_review_intent:
        return RouteDecision(ChatRoute.REVIEWS, order_id, product_id)
    if has_product_intent:
        return RouteDecision(ChatRoute.PRODUCT, order_id, product_id)
    if has_policy_intent:
        return RouteDecision(ChatRoute.POLICY, order_id, product_id)
    if has_order_intent:
        return RouteDecision(ChatRoute.ORDER, order_id, product_id)
    if re.fullmatch(
        r"(?:hi|hello|hey)(?: there)?[!. ]*|"
        r"(?:good morning|good afternoon|good evening)[!. ]*",
        normalized,
    ):
        return RouteDecision(ChatRoute.GREETING, order_id, product_id)
    if re.fullmatch(r"(?:can you help|help me|i need help)[?.! ]*", normalized):
        return RouteDecision(ChatRoute.CLARIFICATION, order_id, product_id)
    return RouteDecision(ChatRoute.OUT_OF_SCOPE, order_id, product_id)


def has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _is_refund_status_request(message: str) -> bool:
    normalized = message.casefold()
    return has_any(normalized, ("refund",)) and has_any(
        normalized,
        (
            "processed",
            "process",
            "status",
            "issued",
            "received",
            "arrived",
            "completed",
            "complete",
        ),
    )


def _is_repeated_delivery_complaint(message: str) -> bool:
    normalized = message.casefold()
    complaint_cues = (
        "third time",
        "again",
        "repeated",
        "tired of this",
        "another delay",
        "once more",
    )
    return has_any(normalized, DELIVERY_WORDS + ARRIVAL_WORDS) and has_any(
        normalized,
        complaint_cues,
    )


def _is_car_purchase_question(message: str) -> bool:
    normalized = message.casefold()
    mentions_vehicle = has_any(normalized, ("car", "vehicle", "automobile"))
    asks_purchase_advice = has_any(
        normalized,
        ("buy", "purchase", "recommend", "should i get"),
    )
    return mentions_vehicle and asks_purchase_advice


def requests_order_search(message: str) -> bool:
    return has_any(message.casefold(), ORDER_SEARCH_WORDS)


def requests_other_order(message: str) -> bool:
    return has_any(message.casefold(), OTHER_ORDER_WORDS)


def _requests_address_change(message: str) -> bool:
    normalized = message.casefold()
    return has_any(
        normalized,
        (
            "change my delivery address",
            "change the delivery address",
            "change delivery address",
            "update my delivery address",
            "update the delivery address",
            "update delivery address",
            "change my address",
            "update my address",
            "redirect my parcel",
        ),
    )


def _route_label(route: ChatRoute) -> str:
    return {
        ChatRoute.ORDER: "Order status",
        ChatRoute.DELIVERY: "Delivery",
        ChatRoute.PAYMENT: "Payment",
    }[route]


def build_default_orchestrator() -> ChatOrchestrator:
    from app.agent.tools import (
        check_cancellation_eligibility_tool,
        check_product_availability_tool,
        find_customer_orders_tool,
        get_delivery_status_tool,
        get_order_status_tool,
        get_payment_status_tool,
        search_customer_reviews_tool,
    )
    from app.rag.service import answer_policy_question

    return ChatOrchestrator(
        order_tool=get_order_status_tool,
        delivery_tool=get_delivery_status_tool,
        payment_tool=get_payment_status_tool,
        product_tool=check_product_availability_tool,
        review_tool=search_customer_reviews_tool,
        cancellation_tool=check_cancellation_eligibility_tool,
        policy_answer=answer_policy_question,
        customer_orders_tool=find_customer_orders_tool,
    )
