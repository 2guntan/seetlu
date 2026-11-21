package sn.seetlu.shopphone.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.nio.ByteBuffer
import java.security.KeyFactory
import java.security.spec.PKCS8EncodedKeySpec
import java.time.Instant
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

object TestSupport {
    fun resource(path: String): String =
        requireNotNull(javaClass.classLoader!!.getResource(path)) { "missing $path" }.readText(Charsets.UTF_8)

    /** The rules the server serves (backend/seetlu/phone/rules.json): both engines are tested on the same file. */
    fun serverRules(): String {
        val candidates = listOf("../../backend/seetlu/phone/rules.json", "../backend/seetlu/phone/rules.json")
        return candidates.map(::File).first { it.exists() }.readText(Charsets.UTF_8)
    }

    val vector: JsonObject by lazy { Json.parseToJsonElement(resource("crypto/test-vector.json")) as JsonObject }

    fun v(key: String): String = vector[key]!!.jsonPrimitive.content

    /** Test-side opener (the phone never holds a private key). */
    fun open(
        privateKeyB64: String,
        blob: ByteArray,
    ): String {
        val buf = ByteBuffer.wrap(blob)
        require(buf.get() == Sealer.VERSION)
        val n = buf.short.toInt()
        val wrapped = ByteArray(n).also { buf.get(it) }
        val iv = ByteArray(12).also { buf.get(it) }
        val body = ByteArray(buf.remaining()).also { buf.get(it) }
        val priv = KeyFactory.getInstance("RSA").generatePrivate(PKCS8EncodedKeySpec(Base64.getDecoder().decode(privateKeyB64)))
        val key =
            Cipher.getInstance("RSA/ECB/OAEPPadding").run {
                init(Cipher.DECRYPT_MODE, priv, Sealer.OAEP)
                doFinal(wrapped)
            }
        return Cipher.getInstance("AES/GCM/NoPadding").run {
            init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, iv))
            String(doFinal(body), Charsets.UTF_8)
        }
    }
}

class FakeQueue : SaleQueue {
    val sales = mutableListOf<PendingSale>()
    val unparsed = mutableListOf<PendingUnparsed>()
    val uploadedUnparsed = mutableSetOf<String>()

    override suspend fun addSale(sale: PendingSale) {
        if (sales.none { it.clientId == sale.clientId }) sales += sale
    }

    override suspend fun addUnparsed(item: PendingUnparsed) {
        unparsed += item
    }

    override suspend fun hasRef(
        source: String,
        ref: String,
    ) = sales.any { it.source == source && it.externalRef == ref }

    override suspend fun pendingSales(limit: Int) = sales.filter { !it.uploaded }.take(limit)

    override suspend fun pendingUnparsed(limit: Int) = unparsed.filter { it.id !in uploadedUnparsed }.take(limit)

    override suspend fun markUploaded(
        saleIds: List<String>,
        unparsedIds: List<String>,
    ) {
        sales.replaceAll { if (it.clientId in saleIds) it.copy(uploaded = true, rawB64 = null) else it }
        uploadedUnparsed += unparsedIds
    }

    override suspend fun recent(
        source: String,
        limit: Int,
    ) = sales.filter { it.source == source }.sortedByDescending { it.occurredAt }.take(limit)

    override suspend fun totalSince(
        source: String,
        since: Instant,
    ) = sales.filter { it.source == source && it.occurredAt >= since }.sumOf { it.amountXof }

    override suspend fun pendingCount() = pendingSales(Int.MAX_VALUE).size + pendingUnparsed(Int.MAX_VALUE).size
}
