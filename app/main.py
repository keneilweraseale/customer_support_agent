from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.api.authorization import router as authorization_router
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.orders import router as orders_router
from app.evaluation.router import router as evaluation_router
from app.evaluation.middleware import EvaluationRequestSizeMiddleware

load_dotenv()

app = FastAPI(title="Customer Support AI Agent", version="0.1.0")
app.add_middleware(EvaluationRequestSizeMiddleware)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(authorization_router)
app.include_router(orders_router)
app.include_router(evaluation_router)
