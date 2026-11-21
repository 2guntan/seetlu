package sn.seetlu.shopphone.core

import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.time.Instant
import java.util.Base64

class CaptureTest {
    private val engine = ParserEngine.fromJson(TestSupport.serverRules())
    private val queue = FakeQueue()
    private val pub = TestSupport.v("public_key_b64")
    private val capture = Capture(queue, { engine }, { pub })
    private val now = Instant.parse("2026-11-21T10:00:00Z")
    private val wave = "Vous avez reçu 5.000F de Awa Diop (77 000 00 00). Réf: T8K2M9QZ"

    @Test
    fun `M9 incoming payment becomes a queued sale with sealed raw text`() =
        runTest {
            assertEquals(Capture.Outcome.SALE, capture.onNotification("com.wave.personal", wave, now))
            val s = queue.sales.single()
            assertEquals("wave", s.source)
            assertEquals(5000L, s.amountXof)
            assertEquals("T8K2M9QZ", s.externalRef)
            assertEquals(engine.rules.version, s.parserVersion)
            assertTrue(s.clientId.matches(Regex("^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")))
            assertEquals(wave, TestSupport.open(TestSupport.v("private_key_b64"), Base64.getDecoder().decode(s.rawB64)))
        }

    @Test
    fun `M9 re-posted notification is counted once`() =
        runTest {
            capture.onNotification("com.wave.personal", wave, now)
            assertEquals(Capture.Outcome.DUPLICATE, capture.onNotification("com.wave.personal", wave, now.plusSeconds(5)))
            assertEquals(1, queue.sales.size)
        }

    @Test
    fun `M9 payment-looking text without a matching rule is uploaded sealed, others ignored`() =
        runTest {
            assertEquals(Capture.Outcome.UNPARSED, capture.onNotification("com.wave.personal", "Paiement reçu de 3.000F", now))
            assertNotNull(queue.unparsed.single().rawB64)
            assertEquals(Capture.Outcome.IGNORED, capture.onNotification("com.whatsapp", wave, now))
            assertEquals(Capture.Outcome.IGNORED, capture.onNotification("com.wave.personal", "Vous avez envoyé 2.000F", now))
            val noKey = Capture(queue, { engine }, { null })
            assertEquals(Capture.Outcome.IGNORED, noKey.onNotification("com.wave.personal", "Paiement reçu de 3.000F", now))
            assertEquals(1, queue.unparsed.size)
        }

    @Test
    fun `M9 quick log pad entries and day total`() =
        runTest {
            capture.quickLog(1500, now)
            capture.quickLog(2500, now.plusSeconds(60))
            assertEquals(4000L, queue.totalSince("quick_log", now))
            assertEquals(2500L, queue.recent("quick_log", 10).first().amountXof)
            assertTrue(runCatching { capture.quickLog(0, now) }.exceptionOrNull() is IllegalArgumentException)
        }

    @Test
    fun `M9 nothing is captured before rules are downloaded`() =
        runTest {
            val none = Capture(queue, { null }, { pub })
            assertEquals(Capture.Outcome.IGNORED, none.onNotification("com.wave.personal", wave, now))
        }
}
