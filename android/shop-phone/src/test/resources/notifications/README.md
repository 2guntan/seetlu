# Notification fixtures

**Placeholder texts.** They were written from the expected shape of Wave and Orange Money
confirmations, not copied from real phones. Before go-live a person must collect real
notification texts on shop phones (docs/12-human-tasks.md), add them here (amounts and
names changed), and fix `backend/seetlu/phone/rules.json` until both test suites pass:

- Python: `backend/tests/test_phone.py` (reference engine)
- Kotlin: `android/shop-phone` unit tests (the engine that runs on the phone)

Each case: `package`, `text`, and `expect` = a sale `{source, amount_xof, external_ref}`,
`"unparsed"` (looks like a payment, no rule matched) or `null` (ignored).
