package sn.seetlu.shopphone.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/** One rule of GET /v1/phone/parsers (docs/08). Package names and regexes are never hard-coded. */
@Serializable
data class ParserRule(
    val id: String,
    val source: String,
    @SerialName("package") val packageName: String,
    val direction: String,
    @SerialName("match_regex") val matchRegex: String,
    @SerialName("amount_group") val amountGroup: String,
    @SerialName("ref_group") val refGroup: String? = null,
    @SerialName("hint_regex") val hintRegex: String? = null,
)

@Serializable
data class ParserRules(
    val version: String,
    val rules: List<ParserRule>,
    @SerialName("raw_public_key_b64") val rawPublicKeyB64: String? = null,
)

sealed interface ParseResult {
    data class Sale(val ruleId: String, val source: String, val amountXof: Long, val externalRef: String?) : ParseResult

    /** Looks like a payment (hint matched) but no rule could read it: uploaded sealed for review. */
    data object Unparsed : ParseResult

    data object Ignored : ParseResult
}

class ParserEngine(val rules: ParserRules) {
    private val options = setOf(RegexOption.DOT_MATCHES_ALL)
    private val compiled =
        rules.rules.filter { it.direction == "in" }.map { r ->
            Triple(r, Regex(r.matchRegex, options), r.hintRegex?.let { Regex(it, options) })
        }

    val packages: Set<String> = compiled.map { it.first.packageName }.toSet()

    fun parse(
        packageName: String,
        text: String,
    ): ParseResult {
        var hinted = false
        for ((rule, match, hint) in compiled) {
            if (rule.packageName != packageName) continue
            val m = match.find(text)
            if (m != null) {
                val amount = amountOf(m.groups[rule.amountGroup]?.value) ?: return ParseResult.Unparsed
                val ref = rule.refGroup?.let { m.groups[it]?.value }
                return ParseResult.Sale(rule.id, rule.source, amount, ref)
            }
            if (hint != null && hint.containsMatchIn(text)) hinted = true
        }
        return if (hinted) ParseResult.Unparsed else ParseResult.Ignored
    }

    companion object {
        val json = Json { ignoreUnknownKeys = true }

        fun fromJson(text: String): ParserEngine = ParserEngine(json.decodeFromString(ParserRules.serializer(), text))

        fun amountOf(text: String?): Long? = text?.filter { it.isDigit() }?.takeIf { it.isNotEmpty() }?.toLongOrNull()
    }
}
