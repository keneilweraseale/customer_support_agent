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
DELIVERY_WORDS = ("delivery", "deliver", "shipment", "tracking", "track")
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
    "how do i",
)
CANCEL_WORDS = ("cancel", "cancellation")
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
    CANCELLATION = "cancellation_check"
    CLARIFICATION = "clarification"


class InvokableTool(Protocol):
    def invoke(self, input: dict[str, str]) -> dict[str, object]: ...


@dataclass(frozen=True)
class RouteDecision:
    route: ChatRoute
    order_id: str | None = None
    product_id: str | None = None


@dataclass(frozen=True)
class OrchestratedChatResult:
    answer: str
    route: ChatRoute
    sources: list[dict[str, str]]
    actions: list[dict[str, str]]
    needs_confirmation: bool = False
    long_term_record_created: bool = False


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
    ) -> None:
        self._order_tool = order_tool
        self._delivery_tool = delivery_tool
        self._payment_tool = payment_tool
        self._product_tool = product_tool
        self._review_tool = review_tool
        self._cancellation_tool = cancellation_tool
        self._policy_answer = policy_answer

    def handle(
        self,
        message: str,
        customer_id: str | None = None,
        context_order_id: str | None = None,
    ) -> OrchestratedChatResult:
        decision = classify_message(message)
        if (
            decision.route
            in {
                ChatRoute.ORDER,
                ChatRoute.DELIVERY,
                ChatRoute.PAYMENT,
                ChatRoute.CANCELLATION,
            }
            and decision.order_id is None
            and context_order_id is not None
        ):
            decision = RouteDecision(
                decision.route,
                order_id=context_order_id,
                product_id=decision.product_id,
            )
        if decision.route == ChatRoute.CLARIFICATION:
            return OrchestratedChatResult(
                answer=self._clarification(decision, message, customer_id),
                route=decision.route,
                sources=[],
                actions=[],
            )

        if decision.route == ChatRoute.POLICY:
            return self._answer_policy(message)

        if decision.route == ChatRoute.MIXED:
            return self._answer_mixed(message, decision)

        if decision.route in (
            ChatRoute.ORDER,
            ChatRoute.DELIVERY,
            ChatRoute.PAYMENT,
            ChatRoute.CANCELLATION,
        ):
            if decision.order_id is None:
                return OrchestratedChatResult(
                    answer=(
                        "Please provide your demo customer ID and order reference "
                        "(for example, verify CUS-DEMO-001, then use ORD-1001)."
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
                        "Please verify a seeded demo customer before I look up private "
                        "order information. This demo flow is not production identity "
                        "verification."
                    ),
                    route=decision.route,
                    sources=[],
                    actions=[],
                )
            if decision.route == ChatRoute.CANCELLATION:
                return self._check_cancellation(decision.order_id, customer_id)

            tool = {
                ChatRoute.ORDER: self._order_tool,
                ChatRoute.DELIVERY: self._delivery_tool,
                ChatRoute.PAYMENT: self._payment_tool,
            }[decision.route]
            result = self._invoke_tool(
                tool,
                {"order_id": decision.order_id, "customer_id": customer_id},
            )
            return self._format_order_result(decision.route, result)

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
            )
            return self._format_product_result(result)

        if decision.route == ChatRoute.REVIEWS:
            product_id = decision.product_id
            query = None if product_id else message
            tool_input = {"product_id": product_id} if product_id else {"query": query}
            result = self._invoke_tool(self._review_tool, tool_input)
            return self._format_review_result(result)

        return OrchestratedChatResult(
            answer="I couldn’t determine what information you need. Could you clarify your question?",
            route=ChatRoute.CLARIFICATION,
            sources=[],
            actions=[],
        )

    def _answer_policy(self, message: str) -> OrchestratedChatResult:
        try:
            result = self._policy_answer(message)
        except ProviderConfigurationError:
            return OrchestratedChatResult(
                answer="Approved policy answers are temporarily unavailable. Please contact support.",
                route=ChatRoute.POLICY,
                sources=[],
                actions=[],
            )
        return OrchestratedChatResult(
            answer=result.answer,
            route=ChatRoute.POLICY,
            sources=result.sources,
            actions=[],
        )

    def _answer_mixed(
        self,
        message: str,
        decision: RouteDecision,
    ) -> OrchestratedChatResult:
        tool_result = self._invoke_tool(
            self._product_tool,
            {"product_id": decision.product_id or ""},
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
            )
        return OrchestratedChatResult(
            answer=(
                f"Policy information: {policy_result.answer}\n\n"
                f"Current product information: {product_answer.answer}"
            ),
            route=ChatRoute.MIXED,
            sources=policy_result.sources,
            actions=[],
        )

    def _check_cancellation(
        self,
        order_id: str,
        customer_id: str,
    ) -> OrchestratedChatResult:
        result = self._invoke_tool(
            self._cancellation_tool,
            {"order_id": order_id, "customer_id": customer_id},
        )
        if result.get("found") is not True:
            return OrchestratedChatResult(
                answer="I couldn’t find that order for this demo customer.",
                route=ChatRoute.CANCELLATION,
                sources=[],
                actions=[],
            )
        if result.get("eligible") is not True:
            return OrchestratedChatResult(
                answer="This order is not eligible for cancellation.",
                route=ChatRoute.CANCELLATION,
                sources=[],
                actions=[],
                long_term_record_created=True,
            )
        token = result.get("confirmation_token")
        if not isinstance(token, str):
            return OrchestratedChatResult(
                answer="I couldn’t prepare a safe cancellation confirmation. No change was made.",
                route=ChatRoute.CANCELLATION,
                sources=[],
                actions=[],
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
        )

    def _invoke_tool(
        self,
        tool: InvokableTool,
        tool_input: dict[str, str],
    ) -> dict[str, object]:
        try:
            result = tool.invoke(tool_input)
        except (DataStoreError, ToolException):
            return {"found": False, "unavailable": True}
        if not isinstance(result, dict):
            return {"found": False, "unavailable": True}
        return result

    def _format_order_result(
        self,
        route: ChatRoute,
        result: dict[str, object],
    ) -> OrchestratedChatResult:
        if result.get("unavailable") is True:
            answer = "Order information is temporarily unavailable. Please try again later."
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
                answer = "; ".join(
                    f"Shipment {item['shipment_id']} is {item['delivery_status']}"
                    + (
                        f", estimated for {item['estimated_delivery']}."
                        if item.get("estimated_delivery")
                        else "."
                    )
                    for item in deliveries
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
                answer = "; ".join(
                    f"Payment {item['payment_id']} is {item['payment_status']}"
                    + (f" (code: {item['error_code']})" if item.get("error_code") else "")
                    for item in payments
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
                return "Please provide your verified demo customer ID and order reference so I can look up private order information."
            return "Please provide your order reference (for example, ORD-1001)."
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

    if has_cancellation_intent:
        if (
            CANCEL_ACTION_PATTERN.search(message)
            and not is_how_to_request
        ) or not has_policy_intent:
            return RouteDecision(ChatRoute.CANCELLATION, order_id, product_id)

    if has_product_intent and has_policy_intent and not product_id:
        return RouteDecision(ChatRoute.CLARIFICATION, order_id, product_id)

    if has_product_intent and has_policy_intent and product_id:
        return RouteDecision(ChatRoute.MIXED, order_id, product_id)

    if has_payment_intent:
        return RouteDecision(ChatRoute.PAYMENT, order_id, product_id)
    if has_delivery_intent:
        return RouteDecision(ChatRoute.DELIVERY, order_id, product_id)
    if has_review_intent:
        return RouteDecision(ChatRoute.REVIEWS, order_id, product_id)
    if has_product_intent:
        return RouteDecision(ChatRoute.PRODUCT, order_id, product_id)
    if has_policy_intent:
        return RouteDecision(ChatRoute.POLICY, order_id, product_id)
    if has_order_intent:
        return RouteDecision(ChatRoute.ORDER, order_id, product_id)
    return RouteDecision(ChatRoute.CLARIFICATION, order_id, product_id)


def has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def build_default_orchestrator() -> ChatOrchestrator:
    from app.agent.tools import (
        check_cancellation_eligibility_tool,
        check_product_availability_tool,
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
    )
