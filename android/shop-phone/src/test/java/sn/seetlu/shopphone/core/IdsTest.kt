package sn.seetlu.shopphone.core

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class IdsTest {
    @Test
    fun `M9 client ids are UUIDv7 and sort by time`() {
        val a = Ids.uuid7(1_700_000_000_000)
        val b = Ids.uuid7(1_700_000_000_001)
        assertEquals(7, a.version())
        assertEquals(2, a.variant())
        assertTrue(a.toString() < b.toString())
    }
}
