package sn.seetlu.shopphone.core

import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import java.time.Instant

class UploaderTest {
    private lateinit var server: MockWebServer
    private lateinit var api: ApiClient
    private val queue = FakeQueue()
    private var token: String? = "dev-id.secret"
    private var unpaired = false
    private val results = mutableListOf<Boolean>()
    private val t0 = Instant.parse("2026-11-21T10:00:00Z")

    @BeforeEach
    fun setUp() {
        server = MockWebServer().also { it.start() }
        api = ApiClient(server.url("").toString().trimEnd('/'), "0.1.0")
    }

    @AfterEach
    fun tearDown() = server.shutdown()

    private fun uploader() =
        Uploader(queue, api, { token }, {
            unpaired = true
            token = null
        }) { ok, _ -> results += ok }

    private fun ok(
        accepted: Int,
        dup: Int = 0,
    ) = MockResponse().setBody("""{"accepted":$accepted,"duplicates":$dup,"unparsed":0}""")

    @Test
    fun `M9 upload sends the queue with the device token and marks it uploaded`() =
        runTest {
            queue.addSale(PendingSale("c1", "wave", 5000, t0, "REF1", "c2VhbGVk", "1"))
            queue.addSale(PendingSale("c2", "quick_log", 1500, t0))
            queue.addUnparsed(PendingUnparsed("u1", "com.wave.personal", t0, "c2VhbGVk"))
            server.enqueue(ok(2))
            val out = uploader().run()
            assertEquals(Uploader.Outcome.Done(2, 0), out)
            val req = server.takeRequest()
            assertEquals("/v1/sales/batch", req.path)
            assertEquals("Bearer dev-id.secret", req.getHeader("Authorization"))
            assertEquals("0.1.0", req.getHeader("X-App-Version"))
            val body = Json.parseToJsonElement(req.body.readUtf8()) as JsonObject
            val first = body["sales"]!!.jsonArray[0].jsonObject
            assertEquals("c1", first["client_id"]!!.jsonPrimitive.content)
            assertEquals("2026-11-21T10:00:00Z", first["occurred_at"]!!.jsonPrimitive.content)
            assertEquals("REF1", first["external_ref"]!!.jsonPrimitive.content)
            assertFalse(body["sales"]!!.jsonArray[1].jsonObject.containsKey("external_ref")) // nulls are omitted
            assertEquals("com.wave.personal", body["unparsed"]!!.jsonArray[0].jsonObject["package_name"]!!.jsonPrimitive.content)
            assertEquals(0, queue.pendingCount())
            assertTrue(queue.sales.all { it.uploaded && it.rawB64 == null })
            assertEquals(listOf(true), results)
        }

    @Test
    fun `M9 more than 200 sales go in several batches`() =
        runTest {
            repeat(450) { queue.addSale(PendingSale("c$it", "quick_log", 100, t0.plusSeconds(it.toLong()))) }
            server.enqueue(ok(200))
            server.enqueue(ok(200))
            server.enqueue(ok(50))
            assertEquals(Uploader.Outcome.Done(450, 0), uploader().run())
            val sizes =
                (1..3).map {
                    (
                        Json.parseToJsonElement(
                            server.takeRequest().body.readUtf8(),
                        ) as JsonObject
                    )["sales"]!!.jsonArray.size
                }
            assertEquals(listOf(200, 200, 50), sizes)
        }

    @Test
    fun `M9 server error keeps the queue for the next try`() =
        runTest {
            queue.addSale(PendingSale("c1", "quick_log", 100, t0))
            server.enqueue(MockResponse().setResponseCode(503))
            assertTrue(uploader().run() is Uploader.Outcome.RetryLater)
            assertEquals(1, queue.pendingCount())
            assertEquals(listOf(false), results)
        }

    @Test
    fun `M9 rejected token unpairs the phone and keeps the queue`() =
        runTest {
            queue.addSale(PendingSale("c1", "quick_log", 100, t0))
            server.enqueue(MockResponse().setResponseCode(401))
            assertEquals(Uploader.Outcome.NotPaired, uploader().run())
            assertTrue(unpaired)
            assertNull(token)
            assertEquals(1, queue.pendingCount())
        }

    @Test
    fun `M9 empty queue sends nothing`() =
        runTest {
            assertEquals(Uploader.Outcome.Done(0, 0), uploader().run())
            assertEquals(0, server.requestCount)
        }

    @Test
    fun `M9 pairing and parser download`() {
        server.enqueue(
            MockResponse().setBody(
                """{"device_token":"d.s","device_id":"d","shop_id":"s","shop_name":"Boutique Awa",
                "timezone":"Africa/Dakar","raw_public_key_b64":"K","parsers_version":"1"}""",
            ),
        )
        val pair = api.pair("482913", "Tecno Spark")
        assertEquals("Boutique Awa", pair.shopName)
        val req = server.takeRequest()
        assertEquals("/v1/phone/pair", req.path)
        assertTrue(req.body.readUtf8().contains("\"code\":\"482913\""))

        server.enqueue(MockResponse().setBody(TestSupport.serverRules()).setHeader("ETag", "\"abc\""))
        val (json, etag) = api.parsers("d.s", null)!!
        assertEquals("\"abc\"", etag)
        assertTrue(ParserEngine.fromJson(json).packages.isNotEmpty())
        server.enqueue(MockResponse().setResponseCode(304))
        assertNull(api.parsers("d.s", etag))
        server.takeRequest()
        assertEquals("\"abc\"", server.takeRequest().getHeader("If-None-Match"))
    }
}
