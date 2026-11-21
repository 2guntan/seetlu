package sn.seetlu.shopphone.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

class UnauthorizedException : IOException("device token rejected")

class ApiException(
    val status: Int,
    message: String,
) : IOException(message)

@Serializable
data class PairIn(
    val code: String,
    val model: String,
    @SerialName("app_version") val appVersion: String,
)

@Serializable
data class PairResult(
    @SerialName("device_token") val deviceToken: String,
    @SerialName("device_id") val deviceId: String,
    @SerialName("shop_id") val shopId: String,
    @SerialName("shop_name") val shopName: String,
    val timezone: String,
    @SerialName("raw_public_key_b64") val rawPublicKeyB64: String? = null,
    @SerialName("parsers_version") val parsersVersion: String,
)

@Serializable
data class SaleJson(
    @SerialName("client_id") val clientId: String,
    val source: String,
    @SerialName("amount_xof") val amountXof: Long,
    @SerialName("occurred_at") val occurredAt: String,
    @SerialName("external_ref") val externalRef: String? = null,
    val raw: String? = null,
    @SerialName("parser_version") val parserVersion: String? = null,
)

@Serializable
data class UnparsedJson(
    @SerialName("package_name") val packageName: String,
    @SerialName("received_at") val receivedAt: String,
    val raw: String,
)

@Serializable
data class BatchJson(
    val sales: List<SaleJson>,
    val unparsed: List<UnparsedJson>,
)

@Serializable
data class BatchResult(
    val accepted: Int,
    val duplicates: Int,
    val unparsed: Int = 0,
)

/** docs/04 phone endpoints. Device token header: `Authorization: Bearer <device id>.<secret>`. */
class ApiClient(
    private val baseUrl: String,
    private val appVersion: String,
    private val http: OkHttpClient = defaultClient(),
) {
    private val json =
        Json {
            ignoreUnknownKeys = true
            explicitNulls = false
        }
    private val jsonType = "application/json".toMediaType()

    fun pair(
        code: String,
        model: String,
    ): PairResult {
        val body = json.encodeToString(PairIn.serializer(), PairIn(code, model, appVersion)).toRequestBody(jsonType)
        val req = Request.Builder().url("$baseUrl/v1/phone/pair").post(body).build()
        http.newCall(req).execute().use { r ->
            if (!r.isSuccessful) throw ApiException(r.code, "pair failed: ${r.code}")
            return json.decodeFromString(PairResult.serializer(), r.body!!.string())
        }
    }

    /** Returns null when the server says 304 (rules unchanged). */
    fun parsers(
        token: String,
        etag: String?,
    ): Pair<String, String?>? {
        val b = Request.Builder().url("$baseUrl/v1/phone/parsers").headers(token)
        if (etag != null) b.header("If-None-Match", etag)
        http.newCall(b.get().build()).execute().use { r ->
            if (r.code == 304) return null
            check(r)
            return r.body!!.string() to r.header("ETag")
        }
    }

    fun uploadBatch(
        token: String,
        batch: BatchJson,
    ): BatchResult {
        val body = json.encodeToString(BatchJson.serializer(), batch).toRequestBody(jsonType)
        val req = Request.Builder().url("$baseUrl/v1/sales/batch").headers(token).post(body).build()
        http.newCall(req).execute().use { r ->
            check(r)
            return json.decodeFromString(BatchResult.serializer(), r.body!!.string())
        }
    }

    private fun Request.Builder.headers(token: String) = header("Authorization", "Bearer $token").header("X-App-Version", appVersion)

    private fun check(r: okhttp3.Response) {
        if (r.code == 401) throw UnauthorizedException()
        if (!r.isSuccessful) throw ApiException(r.code, "HTTP ${r.code}")
    }

    companion object {
        fun defaultClient(): OkHttpClient =
            OkHttpClient
                .Builder()
                .connectTimeout(20, TimeUnit.SECONDS)
                .readTimeout(30, TimeUnit.SECONDS)
                .build()
    }
}
