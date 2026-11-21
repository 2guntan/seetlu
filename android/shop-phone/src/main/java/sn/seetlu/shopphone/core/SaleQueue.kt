package sn.seetlu.shopphone.core

import java.time.Instant

data class PendingSale(
    val clientId: String,
    val source: String,
    val amountXof: Long,
    val occurredAt: Instant,
    val externalRef: String? = null,
    val rawB64: String? = null,
    val parserVersion: String? = null,
    val uploaded: Boolean = false,
)

data class PendingUnparsed(
    val id: String,
    val packageName: String,
    val receivedAt: Instant,
    val rawB64: String,
)

/** Local store: captured sales wait here until uploaded; uploaded ones stay a week for the pad's list. */
interface SaleQueue {
    suspend fun addSale(sale: PendingSale)

    suspend fun addUnparsed(item: PendingUnparsed)

    suspend fun hasRef(
        source: String,
        ref: String,
    ): Boolean

    suspend fun pendingSales(limit: Int): List<PendingSale>

    suspend fun pendingUnparsed(limit: Int): List<PendingUnparsed>

    suspend fun markUploaded(
        saleIds: List<String>,
        unparsedIds: List<String>,
    )

    suspend fun recent(
        source: String,
        limit: Int,
    ): List<PendingSale>

    suspend fun totalSince(
        source: String,
        since: Instant,
    ): Long

    suspend fun pendingCount(): Int
}
