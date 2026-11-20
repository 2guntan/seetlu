"""`make seed` entry point."""

from seetlu.db.session import session_factory
from seetlu.seed.demo import USERS, seed_demo
from seetlu.seed.history import anchor_date, seed_history


def main() -> None:
    with session_factory()() as s:
        result = seed_demo(s)
        anchor = anchor_date()
        n = seed_history(s, result.shop_ids, anchor)
    print(f"seed: account {result.account_id}")
    for shop_id, serial in zip(result.shop_ids, result.kit_serials, strict=True):
        print(f"  shop {shop_id}  kit {serial}")
    print(f"  history: {n} daily reports before {anchor.isoformat()} (SEED_ANCHOR_DATE)")
    print("  logins (dev OTP 000000): " + ", ".join(f"{u['role'].value} {u['phone_e164']}" for u in USERS))


if __name__ == "__main__":
    main()
