package sn.seetlu.shopphone.core

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Test
import java.util.Base64

class SealerTest {
    @Test
    fun `M9 sealed text opens with the private key and hides the plaintext`() {
        val text = "Vous avez reçu 25.000 FCFA. Trans ID: MP241121.1532.A12345"
        val blob = Sealer.seal(TestSupport.v("public_key_b64"), text)
        assertEquals(Sealer.VERSION, blob[0])
        assertFalse(String(blob, Charsets.ISO_8859_1).contains("25.000"))
        assertEquals(text, TestSupport.open(TestSupport.v("private_key_b64"), blob))
    }

    @Test
    fun `M9 same blob layout as the Python server`() {
        val fromPython = Base64.getDecoder().decode(TestSupport.v("sealed_by_python_b64"))
        assertEquals(TestSupport.v("plaintext"), TestSupport.open(TestSupport.v("private_key_b64"), fromPython))
    }

    @Test
    fun `M9 no key means no raw text is kept`() {
        assertNull(Sealer.sealB64(null, "x"))
        assertNull(Sealer.sealB64("", "x"))
    }
}
