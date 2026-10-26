from starlette.responses import JSONResponse

from app.evaluation.config import get_evaluation_settings


class EvaluationRequestSizeMiddleware:
    """Bound request-body buffering for evaluation endpoints only."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/eval/"):
            await self.app(scope, receive, send)
            return

        maximum_bytes = get_evaluation_settings().max_request_body_bytes
        content_length = next(
            (
                value.decode("latin-1")
                for key, value in scope.get("headers", [])
                if key.lower() == b"content-length"
            ),
            None,
        )
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                declared_length = 0
            if declared_length > maximum_bytes:
                await self._too_large(scope, receive, send)
                return

        messages = []
        body_size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            messages.append(message)
            body_size += len(message.get("body", b""))
            if body_size > maximum_bytes:
                await self._too_large(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        async def replay_receive():
            if messages:
                return messages.pop(0)
            return await receive()

        await self.app(scope, replay_receive, send)

    async def _too_large(self, scope, receive, send) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "request_too_large",
                    "message": "Evaluation request exceeds the configured size limit.",
                }
            },
        )
        await response(scope, receive, send)
