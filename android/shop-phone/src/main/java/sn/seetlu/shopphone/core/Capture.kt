package sn.seetlu.shopphone.core

import java.time.Instant

/** Turns a notification into a queued sale, a sealed "unparsed" item, or nothing (docs/08). */
class Capture(
    private val queue: SaleQueue,
    private val engine: () -> ParserEngine?,
    private val publicKey: () -> String?,
) {
    enum class Outcome { SALE, DUPLICATE, UNPARSED, IGNORED }

    suspend fun onNotification(
        packageName: String,
        text: String,
        postedAt: Instant,
    ): Outcome {
        val e = engine() ?: return Outcome.IGNORED
        if (packageName !in e.packages) return Outcome.IGNORED
        return when (val r = e.parse(packageName, text)) {
            is ParseResult.Sale -> {
                // the same notification is often re-posted (updates, reboots): one sale per reference
                if (r.externalRef != null && queue.hasRef(r.source, r.externalRef)) return Outcome.DUPLICATE
                queue.addSale(
                    PendingSale(
                        clientId = Ids.uuid7().toString(),
                        source = r.source,
                        amountXof = r.amountXof,
                        occurredAt = postedAt,
                        externalRef = r.externalRef,
                        rawB64 = Sealer.sealB64(publicKey(), text),
                        parserVersion = e.rules.version,
                    ),
                )
                Outcome.SALE
            }
            ParseResult.Unparsed -> {
                // never upload plain text: without the server key, unparsed items are dropped
                val sealed = Sealer.sealB64(publicKey(), text) ?: return Outcome.IGNORED
                queue.addUnparsed(PendingUnparsed(Ids.uuid7().toString(), packageName, postedAt, sealed))
                Outcome.UNPARSED
            }
            ParseResult.Ignored -> Outcome.IGNORED
        }
    }

    suspend fun quickLog(
        amountXof: Long,
        now: Instant,
    ): PendingSale {
        require(amountXof in 1..10_000_000) { "amount out of range" }
        val sale = PendingSale(Ids.uuid7().toString(), "quick_log", amountXof, now)
        queue.addSale(sale)
        return sale
    }
}
