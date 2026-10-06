import asyncio
import functools
import os
import random
import time
from dataclasses import dataclass

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from openai import AsyncOpenAI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field


POLICY = """
CUSTOMER SUPPORT POLICY

Returns: Customers may return unused products in their original packaging within
30 days of delivery. Final-sale products cannot be returned.

Damaged products: A damaged or defective product must be reported within 7 days
of delivery. The customer should include a photo of the damage.

Refunds: Approved refunds are sent to the original payment method within 5 to 10
business days after the returned product is inspected. Gift cards are not refundable.

Exchanges: Unused products can be exchanged for another size or colour within
30 days. If the requested replacement is unavailable, the customer receives a refund.

Cancellations: An order can be cancelled before it has been shipped. After
shipping, the normal return policy applies.

Delivery: Standard delivery takes 3 to 5 business days. Express delivery takes
1 to 2 business days. International delivery takes 7 to 14 business days, and
the customer is responsible for customs fees.

Missing packages: If tracking shows delivered but the package is missing, the
customer must contact support within 3 days so that an investigation can be opened.

Subscriptions: A subscription can be cancelled before the next billing date.
Payments already charged are not prorated or automatically refunded.

Accounts and privacy: Password-reset links expire after 30 minutes. Support will
never ask for a password. Account-deletion requests are completed within 30 days,
but order records may be retained for 7 years where required by law.

Support hours: Human support is available Monday to Friday, 09:00 to 17:00 UTC.
Questions not covered by this policy must be escalated to a human support agent.
""".strip()


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://tutorial:tutorial@postgres:5432/observability",
)
LLM_MODE = os.getenv("LLM_MODE", "mock").lower()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-astra")
OTLP_ENDPOINT = os.getenv(
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "http://tempo:4318/v1/traces",
)


def configure_tracing() -> trace.Tracer:
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "llm-support",
                "service.version": "1.0.0",
            }
        )
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP_ENDPOINT))
    )
    trace.set_tracer_provider(provider)
    return trace.get_tracer("llm-support")


tracer = configure_tracing()


def traced(span_name: str):
    """Create a span around a small asynchronous function."""

    def decorator(function):
        @functools.wraps(function)
        async def wrapper(*args, **kwargs):
            with tracer.start_as_current_span(span_name) as span:
                try:
                    return await function(*args, **kwargs)
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise

        return wrapper

    return decorator


REQUESTS = Counter(
    "llm_requests_total",
    "Number of support-assistant requests.",
    ["status"],
)
ERRORS = Counter(
    "llm_errors_total",
    "Number of support-assistant errors.",
    ["error_type"],
)
TOKENS = Counter(
    "llm_tokens_total",
    "Number of approximate or provider-reported LLM tokens.",
    ["type"],
)
DURATION = Histogram(
    "llm_response_duration_seconds",
    "End-to-end support-assistant response time.",
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)


app = FastAPI(
    title="LLM Support Observability Tutorial",
    description="A tiny support assistant instrumented with metrics and traces.",
)


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    simulate_error: bool = False


class ChatResponse(BaseModel):
    answer: str
    input_tokens: int
    output_tokens: int
    trace_id: str


@dataclass
class LLMResult:
    answer: str
    input_tokens: int
    output_tokens: int


def estimate_tokens(text: str) -> int:
    return max(1, round(len(text.split()) * 1.3))


def mock_answer(question: str) -> str:
    text = question.lower()
    if "final sale" in text:
        fact = "Final-sale products cannot be returned."
    elif "gift card" in text:
        fact = "Gift cards are not refundable."
    elif "subscription" in text or "billing" in text:
        fact = (
            "A subscription can be cancelled before the next billing date, but "
            "payments already charged are not prorated or automatically refunded."
        )
    elif any(word in text for word in ("damaged", "broken", "defective")):
        fact = (
            "A damaged or defective product must be reported within 7 days of "
            "delivery, and you should include a photo of the damage."
        )
    elif any(word in text for word in ("exchange", "size", "colour", "color")):
        fact = (
            "Unused products can be exchanged for another size or colour within "
            "30 days. If the replacement is unavailable, you receive a refund."
        )
    elif any(word in text for word in ("return", "send back")):
        fact = (
            "You may return an unused product in its original packaging within "
            "30 days of delivery."
        )
    elif any(word in text for word in ("refund", "money back")):
        fact = (
            "An approved refund is sent to the original payment method within "
            "5 to 10 business days after the return is inspected."
        )
    elif any(word in text for word in ("cancel order", "cancel my order")):
        fact = (
            "An order can be cancelled before it has been shipped. After shipping, "
            "the normal return policy applies."
        )
    elif "express" in text:
        fact = "Express delivery takes 1 to 2 business days."
    elif any(word in text for word in ("international", "customs", "abroad")):
        fact = (
            "International delivery takes 7 to 14 business days, and the customer "
            "is responsible for customs fees."
        )
    elif any(word in text for word in ("missing", "marked delivered", "not arrived")):
        fact = (
            "If tracking shows delivered but the package is missing, contact support "
            "within 3 days so an investigation can be opened."
        )
    elif any(word in text for word in ("delivery", "shipping", "tracking", "arrive")):
        fact = "Standard delivery takes 3 to 5 business days."
    elif any(word in text for word in ("password", "reset link")):
        fact = (
            "Password-reset links expire after 30 minutes, and support will never "
            "ask for your password."
        )
    elif any(word in text for word in ("delete account", "personal data", "privacy")):
        fact = (
            "Account-deletion requests are completed within 30 days, but order "
            "records may be retained for 7 years where required by law."
        )
    elif any(word in text for word in ("human", "support hours", "opening hours")):
        fact = "Human support is available Monday to Friday, 09:00 to 17:00 UTC."
    else:
        return random.choice(
            (
                "Sorry, I can't answer that from the customer-support policy. "
                "Please contact a human support agent.",
                "I'm unable to help with that because it is outside the support "
                "policy. Please contact a human support agent.",
                "I apologise, but this request is not covered by the policy. "
                "A human support agent can help you further.",
            )
        )

    return f"I can help with that. {fact}"


@traced("llm.call")
async def call_llm(request: ChatRequest) -> LLMResult:
    span = trace.get_current_span()
    span.set_attribute("llm.mode", LLM_MODE)
    span.set_attribute("llm.model", "mock-support-v1" if LLM_MODE == "mock" else OPENAI_MODEL)
    span.set_attribute("llm.question", request.question)

    if request.simulate_error:
        await asyncio.sleep(0.15)
        raise RuntimeError("Simulated LLM provider error")

    if LLM_MODE == "mock":
        await asyncio.sleep(random.uniform(0.2, 1.2))
        answer = mock_answer(request.question)
        result = LLMResult(
            answer=answer,
            input_tokens=estimate_tokens(POLICY + request.question),
            output_tokens=estimate_tokens(answer),
        )
    elif LLM_MODE == "openai":
        client = AsyncOpenAI()
        response = await client.responses.create(
            model=OPENAI_MODEL,
            instructions=(
                "You are a concise customer-support assistant. Follow the supplied "
                "policy and use it as your only source of facts. If the question is "
                "outside the policy, do not answer it from general knowledge. Briefly "
                "refuse by saying that you cannot help with that request and direct "
                "the customer to a human support agent."
            ),
            input=f"POLICY:\n{POLICY}\n\nCUSTOMER QUESTION:\n{request.question}",
        )
        usage = response.usage
        answer = response.output_text
        result = LLMResult(
            answer=answer,
            input_tokens=getattr(usage, "input_tokens", estimate_tokens(POLICY + request.question)),
            output_tokens=getattr(usage, "output_tokens", estimate_tokens(answer)),
        )
    else:
        raise RuntimeError(f"Unsupported LLM_MODE: {LLM_MODE}")

    span.set_attribute("llm.input_tokens", result.input_tokens)
    span.set_attribute("llm.output_tokens", result.output_tokens)
    span.set_attribute("llm.total_tokens", result.input_tokens + result.output_tokens)
    span.set_attribute("llm.answer", result.answer)
    return result


def save_interaction(
    *,
    question: str,
    answer: str,
    input_tokens: int,
    output_tokens: int,
    duration_seconds: float,
    status: str,
    error: str | None,
    trace_id: str,
) -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO interactions (
                    question, answer, policy_text, input_tokens, output_tokens,
                    duration_seconds, status, error, trace_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    question,
                    answer,
                    POLICY,
                    input_tokens,
                    output_tokens,
                    duration_seconds,
                    status,
                    error,
                    trace_id,
                ),
            )


@traced("chat.request")
async def handle_chat(request: ChatRequest) -> ChatResponse:
    started = time.perf_counter()
    span = trace.get_current_span()
    trace_id = f"{span.get_span_context().trace_id:032x}"
    span.set_attribute("app.trace_id", trace_id)

    try:
        result = await call_llm(request)
        duration = time.perf_counter() - started
        await asyncio.to_thread(
            save_interaction,
            question=request.question,
            answer=result.answer,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            duration_seconds=duration,
            status="success",
            error=None,
            trace_id=trace_id,
        )
        REQUESTS.labels("success").inc()
        TOKENS.labels("input").inc(result.input_tokens)
        TOKENS.labels("output").inc(result.output_tokens)
        return ChatResponse(
            answer=result.answer,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            trace_id=trace_id,
        )
    except Exception as exc:
        duration = time.perf_counter() - started
        error_type = "simulated_error" if request.simulate_error else "llm_error"
        REQUESTS.labels("error").inc()
        ERRORS.labels(error_type).inc()
        try:
            await asyncio.to_thread(
                save_interaction,
                question=request.question,
                answer="",
                input_tokens=0,
                output_tokens=0,
                duration_seconds=duration,
                status="error",
                error=str(exc),
                trace_id=trace_id,
            )
        except Exception as database_exc:
            ERRORS.labels("database_error").inc()
            span.record_exception(database_exc)
        raise HTTPException(status_code=500, detail="The demo LLM call failed") from exc
    finally:
        DURATION.observe(time.perf_counter() - started)


@app.get("/")
def index():
    return {
        "message": "LLM Support Observability Tutorial",
        "docs": "/docs",
        "metrics": "/metrics",
        "llm_mode": LLM_MODE,
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    return await handle_chat(request)
