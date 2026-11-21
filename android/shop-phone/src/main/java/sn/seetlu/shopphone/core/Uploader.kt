package sn.seetlu.shopphone.core

import java.io.IOException
import java.time.Instant

/** Sends the queue in batches of 200 (docs/04 maxItems) until it is empty. */
class Uploader(
    private val queue: SaleQueue,
    private val api: ApiClient,
    private val token: () -> String?,
    private val onUnpaired: () -> Unit,
    private val onResult: (ok: Boolean, at: Instant) -> Unit = { _, _ -> },
) {
    sealed interface Outcome {
        data class Done(val accepted: Int, val duplicates: Int) : Outcome

        data object NotPaired : Outcome

        data class RetryLater(val reason: String) : Outcome
    }

    suspend fun run(now: Instant = Instant.now()): Outcome {
        val tok = token() ?: return Outcome.NotPaired
        var accepted = 0
        var duplicates = 0
        try {
            while (true) {
                val sales = queue.pendingSales(BATCH)
                val unparsed = queue.pendingUnparsed(BATCH)
                if (sales.isEmpty() && unparsed.isEmpty()) break
                val result =
                    api.uploadBatch(
                        tok,
                        BatchJson(
                            sales.map {
                                SaleJson(
                                    it.clientId,
                                    it.source,
                                    it.amountXof,
                                    it.occurredAt.toString(),
                                    it.externalRef,
                                    it.rawB64,
                                    it.parserVersion,
                                )
                            },
                            unparsed.map { UnparsedJson(it.packageName, it.receivedAt.toString(), it.rawB64) },
                        ),
                    )
                queue.markUploaded(sales.map { it.clientId }, unparsed.map { it.id })
                accepted += result.accepted
                duplicates += result.duplicates
                if (sales.size < BATCH && unparsed.size < BATCH) break
            }
        } catch (e: UnauthorizedException) {
            onUnpaired()
            onResult(false, now)
            return Outcome.NotPaired
        } catch (e: ApiException) {
            onResult(false, now)
            return Outcome.RetryLater("HTTP ${e.status}")
        } catch (e: IOException) {
            onResult(false, now)
            return Outcome.RetryLater(e.message ?: "network")
        }
        onResult(true, now)
        return Outcome.Done(accepted, duplicates)
    }

    companion object {
        const val BATCH = 200
    }
}
