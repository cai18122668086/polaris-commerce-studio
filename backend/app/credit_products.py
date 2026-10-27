"""Server-owned commercial catalog approved in the account-center review."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    amount_fen: int
    credits: int
    kind: str
    plan_id: str | None = None
    months: int = 0
    validity_months: int = 0

    def snapshot(self) -> dict:
        return asdict(self)


# Preserve the previously offered pack and every pending order's original terms.
# The other pack prices in the prototype were never approved as final products.
PRODUCTS = {
    "credits_1500": Product(
        "credits_1500",
        "创作积分包 · 1,500 积分",
        9900,
        1500,
        "pack",
        validity_months=0,
    ),
}
for plan_id, name, credits, monthly, annual in (
    ("light", "轻享版", 600, 4900, 46800),
    ("pro", "专业版", 1500, 9900, 94800),
    ("team", "团队版", 5000, 29900, 286800),
):
    for period, months, price in (("monthly", 1, monthly), ("annual", 12, annual)):
        product_id = f"{plan_id}_{period}"
        PRODUCTS[product_id] = Product(
            product_id,
            f"{name} · {'年付' if months == 12 else '月付'}",
            price,
            credits,
            "membership",
            plan_id,
            months,
        )
