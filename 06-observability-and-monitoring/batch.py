import os
import re
import time

import psycopg
from openai import OpenAI


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://tutorial:tutorial@postgres:5432/observability",
)
BATCH_INTERVAL_SECONDS = int(os.getenv("BATCH_INTERVAL_SECONDS", "15"))
LLM_MODE = os.getenv("LLM_MODE", "mock").lower()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-astra")
OPENAI_JUDGE_MODEL = os.getenv("OPENAI_JUDGE_MODEL") or OPENAI_MODEL
JUDGE_CLIENT = OpenAI() if LLM_MODE == "openai" else None

REJECTION_PATTERN = re.compile(
    r"\b(?:sorry|apologi[sz]e|cannot|can't|unable)\b.{0,80}"
    r"\b(?:help|answer|assist|provide|covered)\b"
    r"|\b(?:outside|beyond)\s+(?:my|the)\s+scope\b"
    r"|\bnot covered by (?:the |this )?policy\b",
    re.IGNORECASE | re.DOTALL,
)


def calculate_response_length(answer: str) -> int:
    return len(answer)


def calculate_rejection(answer: str) -> bool:
    return bool(REJECTION_PATTERN.search(answer))


def calculate_helpfulness(question: str, answer: str) -> str:
    if LLM_MODE == "mock":
        return "NA"
    if LLM_MODE != "openai" or JUDGE_CLIENT is None:
        raise RuntimeError(f"Unsupported LLM_MODE: {LLM_MODE}")

    response = JUDGE_CLIENT.responses.create(
        model=OPENAI_JUDGE_MODEL,
        instructions=(
            "You evaluate customer-support answers. Label an answer helpful when it "
            "does at least one of these: directly resolves the user's question; gives "
            "a relevant concrete next step. Otherwise label it not-helpful."
            "Return exactly one label: helpful or not-helpful."
            "Do not add an explanation."
        ),
        input=f"USER QUESTION:\n{question}\n\nASSISTANT ANSWER:\n{answer}",
    )
    label = response.output_text.strip().lower().strip("`'\". ")
    if label not in {"helpful", "not-helpful"}:
        raise ValueError(f"Unexpected helpfulness label: {label!r}")
    return label


def evaluate_pending() -> int:
    evaluated = 0
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT i.id, i.question, i.answer
                FROM interactions AS i
                LEFT JOIN evaluations AS e ON e.interaction_id = i.id
                WHERE i.status = 'success' AND e.interaction_id IS NULL
                ORDER BY i.created_at
                LIMIT 100
                """
            )
            rows = cursor.fetchall()
            for interaction_id, question, answer in rows:
                try:
                    helpfulness = calculate_helpfulness(question, answer)
                except Exception as exc:
                    print(
                        f"Helpfulness judge failed; interaction_id={interaction_id}; "
                        f"error={exc}",
                        flush=True,
                    )
                    continue

                cursor.execute(
                    """
                    INSERT INTO evaluations (
                        interaction_id, response_length, is_rejection, helpfulness
                    )
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (interaction_id) DO NOTHING
                    """,
                    (
                        interaction_id,
                        calculate_response_length(answer),
                        calculate_rejection(answer),
                        helpfulness,
                    ),
                )
                evaluated += cursor.rowcount
    return evaluated


def main() -> None:
    print(f"Batch evaluator started; interval={BATCH_INTERVAL_SECONDS}s", flush=True)
    while True:
        try:
            count = evaluate_pending()
            print(f"Batch complete; evaluated={count}", flush=True)
        except Exception as exc:
            print(f"Batch failed: {exc}", flush=True)
        time.sleep(BATCH_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
