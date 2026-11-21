package sn.seetlu.shopphone.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.DynamicTest
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.TestFactory

class ParserEngineTest {
    private val engine = ParserEngine.fromJson(TestSupport.serverRules())

    @TestFactory
    fun `M9 parser rules on notification fixtures`(): List<DynamicTest> {
        val cases = Json.parseToJsonElement(TestSupport.resource("notifications/placeholder-cases.json")) as JsonArray
        return cases.map { it.jsonObject }.map { c ->
            DynamicTest.dynamicTest(c["name"]!!.jsonPrimitive.content) {
                val got = engine.parse(c["package"]!!.jsonPrimitive.content, c["text"]!!.jsonPrimitive.content)
                when (val want = c["expect"]) {
                    null, JsonNull -> assertEquals(ParseResult.Ignored, got)
                    is JsonPrimitive -> assertEquals(ParseResult.Unparsed, got)
                    is JsonObject -> {
                        val sale = got as ParseResult.Sale
                        assertEquals(want["source"]!!.jsonPrimitive.content, sale.source)
                        assertEquals(want["amount_xof"]!!.jsonPrimitive.long, sale.amountXof)
                        assertEquals(want["external_ref"]!!.jsonPrimitive.content, sale.externalRef)
                    }
                    else -> error("bad fixture")
                }
            }
        }
    }

    @Test
    fun `M9 packages come from the rules, not from code`() {
        assertTrue("com.wave.personal" in engine.packages)
        val custom =
            ParserEngine.fromJson(
                """{"version":"9","rules":[{"id":"x","source":"wave","package":"com.example.pay","direction":"in",
                "match_regex":"got (?<amount>[0-9 ]+) F","amount_group":"amount"}]}""",
            )
        assertEquals(setOf("com.example.pay"), custom.packages)
        assertEquals(ParseResult.Sale("x", "wave", 1500, null), custom.parse("com.example.pay", "got 1 500 F"))
    }

    @Test
    fun `M9 amount keeps digits only`() {
        assertEquals(262500L, ParserEngine.amountOf("262 500"))
        assertEquals(5000L, ParserEngine.amountOf("5.000"))
        assertEquals(null, ParserEngine.amountOf(" F "))
    }
}
