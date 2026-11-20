"""`make seed` entry point."""

from seetlu.db.session import session_factory
from seetlu.seed.demo import USERS, seed_demo


def main() -> None:
    with session_factory()() as s:
        result = seed_demo(s)
    print(f"seed: account {result.account_id}")
    for shop_id, serial in zip(result.shop_ids, result.kit_serials, strict=True):
        print(f"  shop {shop_id}  kit {serial}")
    print("  logins (dev OTP 000000): " + ", ".join(f"{u['role'].value} {u['phone_e164']}" for u in USERS))


if __name__ == "__main__":
    main()
