import json
from types import SimpleNamespace

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from app.agent.tool_calling import GroqToolCallingAgent


class OrderLookupInput(BaseModel):
    order_id: str
    customer_id: str


class ProductLookupInput(BaseModel):
    product_id: str


class CancellationInput(BaseModel):
    order_id: str


class FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.function = SimpleNamespace(name=name, arguments=arguments)

    def model_dump(self, exclude_none: bool = True) -> dict[str, object]:
        del exclude_none
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.function.name,
                "arguments": self.function.arguments,
            },
        }


class FakeGroqCompletions:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.requests: list[dict[str, object]] = []

    def create(self, **request: object) -> object:
        self.requests.append(request)
        return self.responses.pop(0)


def _response(content: str | None, tool_calls: list[FakeToolCall] | None = None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=tool_calls)
            )
        ]
    )


def test_agent_executes_tool_with_server_authenticated_customer_id() -> None:
    tool_inputs: list[dict[str, str]] = []

    def get_order_status(order_id: str, customer_id: str) -> dict[str, object]:
        tool_inputs.append({"order_id": order_id, "customer_id": customer_id})
        return {"found": True, "order_id": order_id, "order_status": "shipped"}

    tool = StructuredTool.from_function(
        func=get_order_status,
        name="get_order_status",
        description="Read an order status.",
        args_schema=OrderLookupInput,
    )
    agent = GroqToolCallingAgent("test-key", "test-model", [tool])
    completions = FakeGroqCompletions(
        [
            _response(
                None,
                [
                    FakeToolCall(
                        "call-1",
                        "get_order_status",
                        json.dumps(
                            {
                                "order_id": "ORD-1001",
                                "customer_id": "CUS-ATTACKER",
                            }
                        ),
                    )
                ],
            ),
            _response("Order ORD-1001 is shipped."),
        ]
    )
    agent._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    result = agent.run("Where is order ORD-1001?", "CUS-VERIFIED-1")

    assert result.answer == "Order ORD-1001 is shipped."
    assert tool_inputs == [
        {"order_id": "ORD-1001", "customer_id": "CUS-VERIFIED-1"}
    ]
    exposed_schema = completions.requests[0]["tools"][0]["function"]["parameters"]
    assert "customer_id" not in exposed_schema["properties"]
    assert "customer_id" not in exposed_schema["required"]
    assert result.executions[0].result["order_status"] == "shipped"


def test_agent_excludes_cancellation_tools_and_private_tools_without_auth() -> None:
    def find_product(product_id: str) -> dict[str, object]:
        return {"found": True, "product_id": product_id}

    def cancel_order(order_id: str) -> dict[str, object]:
        return {"cancelled": True, "order_id": order_id}

    public_tool = StructuredTool.from_function(
        func=find_product,
        name="check_product_availability",
        description="Read product availability.",
        args_schema=ProductLookupInput,
    )
    cancellation_tool = StructuredTool.from_function(
        func=cancel_order,
        name="cancel_order",
        description="Cancel an order.",
        args_schema=CancellationInput,
    )
    agent = GroqToolCallingAgent(
        "test-key",
        "test-model",
        [public_tool, cancellation_tool],
    )
    completions = FakeGroqCompletions([_response("Please provide a product ID.")])
    agent._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    result = agent.run("Is a product available?")

    exposed_names = {
        tool["function"]["name"] for tool in completions.requests[0]["tools"]
    }
    assert exposed_names == {"check_product_availability"}
    assert "cancel_order" not in agent._tools
    assert result.executions == []
    assert result.answer == "Please provide a product ID."
