package sn.seetlu.shopphone.core

import java.security.SecureRandom
import java.util.UUID

/** UUIDv7 (RFC 9562), the idempotency key of every sale (CLAUDE.md: UUIDv7 everywhere). */
object Ids {
    private val random = SecureRandom()

    fun uuid7(nowMs: Long = System.currentTimeMillis()): UUID {
        val b = ByteArray(16).also { random.nextBytes(it) }
        var ms = nowMs
        for (i in 5 downTo 0) {
            b[i] = (ms and 0xff).toByte()
            ms = ms shr 8
        }
        b[6] = ((b[6].toInt() and 0x0f) or 0x70).toByte()
        b[8] = ((b[8].toInt() and 0x3f) or 0x80).toByte()
        var hi = 0L
        var lo = 0L
        for (i in 0 until 8) hi = (hi shl 8) or (b[i].toLong() and 0xff)
        for (i in 8 until 16) lo = (lo shl 8) or (b[i].toLong() and 0xff)
        return UUID(hi, lo)
    }
}
