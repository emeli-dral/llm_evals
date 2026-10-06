import os
import random
import time

import httpx


APP_URL = os.getenv("APP_URL", "http://app:8000")
LOADGEN_INTERVAL_SECONDS = float(os.getenv("LOADGEN_INTERVAL_SECONDS", "2"))
LOADGEN_REPEAT = os.getenv("LOADGEN_REPEAT", "true").lower() == "true"
ERROR_PROBABILITY = float(os.getenv("ERROR_PROBABILITY", "0.08"))

QUESTIONS = [
    "Can I return a product after 20 days?",
    "What condition must an item be in for a return?",
    "Do I need the original packaging to send something back?",
    "Can I return an item after 45 days?",
    "Are final-sale products returnable?",
    "I bought the wrong item. Can I send it back?",
    "My product arrived damaged. What should I do?",
    "How quickly must I report a broken item?",
    "Do you need a photo of a defective product?",
    "The item stopped working on the first day. Can you help?",
    "When will my refund arrive?",
    "Where will my refund be sent?",
    "Can you refund me in cash instead?",
    "Why has my refund not appeared after three days?",
    "Can I get a refund for a gift card?",
    "Can I exchange a shirt for another size?",
    "Can I exchange an unused item for another colour?",
    "What happens if the replacement size is unavailable?",
    "Can I exchange an item after 25 days?",
    "I want to cancel my order before it ships.",
    "Can I cancel my order after it has shipped?",
    "How long does standard delivery take?",
    "How long does express delivery take?",
    "When should my package arrive?",
    "Do you provide tracking for delivery?",
    "How long does international shipping take?",
    "Who pays customs fees on an international order?",
    "Can you ship my order abroad?",
    "Tracking says delivered, but the package is missing.",
    "How soon should I report a package marked delivered but not received?",
    "My parcel has not arrived. What do I do?",
    "How do I cancel my subscription?",
    "Can I cancel before the next billing date?",
    "Will you prorate my subscription payment?",
    "Can I get this month's subscription charge refunded automatically?",
    "How long does a password reset link work?",
    "Will support ever ask me for my password?",
    "My reset link expired. What should I do?",
    "How do I delete my account?",
    "How long does account deletion take?",
    "Why do you keep order records after account deletion?",
    "What happens to my personal data when I delete my account?",
    "When can I speak to a human support agent?",
    "What are your support opening hours?",
    "Is human support available at the weekend?",
    "Can you repair a product two years after purchase?",
    "Do you offer loyalty points?",
    "Can you price-match another store?",
    "Do you offer a lifetime warranty?",
    "Can I pay using cryptocurrency?",
    "What will the weather be in London tomorrow?",
    "Can you write a Python function that sorts a list?",
    "Who won the football match last night?",
    "Puis-je retourner un produit après vingt jours ?",
    "Combien de temps prend la livraison express ?",
    "¿Puedo cancelar mi pedido antes del envío?",
]


def main() -> None:
    mode = "repeat" if LOADGEN_REPEAT else "one pass"
    print(
        f"Load generator started; questions={len(QUESTIONS)}; mode={mode}",
        flush=True,
    )
    with httpx.Client(base_url=APP_URL, timeout=30) as client:
        while True:
            questions = random.sample(QUESTIONS, k=len(QUESTIONS))
            for index, question in enumerate(questions):
                payload = {
                    "question": question,
                    "simulate_error": random.random() < ERROR_PROBABILITY,
                }
                try:
                    response = client.post("/chat", json=payload)
                    print(
                        f"status={response.status_code} "
                        f"error={payload['simulate_error']} "
                        f"question={question!r}",
                        flush=True,
                    )
                except Exception as exc:
                    print(f"Request failed: {exc}", flush=True)

                if index < len(questions) - 1 or LOADGEN_REPEAT:
                    time.sleep(LOADGEN_INTERVAL_SECONDS)

            if not LOADGEN_REPEAT:
                print("One pass completed; load generator stopped", flush=True)
                return


if __name__ == "__main__":
    main()
