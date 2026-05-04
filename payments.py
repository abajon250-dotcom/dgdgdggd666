import stripe

stripe.api_key = "sk_test_51..."  # Вставьте свой тестовый ключ

def create_payment_intent(amount: float, currency: str = "usd"):
    return stripe.PaymentIntent.create(
        amount=int(amount * 100),
        currency=currency,
        metadata={"integration": "eSIM_bot"}
    )