package sn.seetlu.shopphone.core

import java.nio.ByteBuffer
import java.security.KeyFactory
import java.security.SecureRandom
import java.security.spec.MGF1ParameterSpec
import java.security.spec.X509EncodedKeySpec
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.OAEPParameterSpec
import javax.crypto.spec.PSource

/**
 * Seals raw notification text with the server public key (docs/09); the phone can never read it back.
 * Blob: 0x01 | key length (2 bytes) | RSA-OAEP(SHA-256, MGF1-SHA-256)(AES key) | IV (12) | AES-256-GCM ciphertext+tag.
 * Same layout as backend/seetlu/phone/crypto.py.
 */
object Sealer {
    const val VERSION: Byte = 1
    val OAEP: OAEPParameterSpec =
        OAEPParameterSpec("SHA-256", "MGF1", MGF1ParameterSpec.SHA256, PSource.PSpecified.DEFAULT)
    private val random = SecureRandom()

    fun seal(
        publicKeyB64: String,
        text: String,
    ): ByteArray {
        val pub = KeyFactory.getInstance("RSA").generatePublic(X509EncodedKeySpec(Base64.getDecoder().decode(publicKeyB64)))
        val aes = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val iv = ByteArray(12).also { random.nextBytes(it) }
        val wrapped =
            Cipher.getInstance("RSA/ECB/OAEPPadding").run {
                init(Cipher.ENCRYPT_MODE, pub, OAEP)
                doFinal(aes.encoded)
            }
        val body =
            Cipher.getInstance("AES/GCM/NoPadding").run {
                init(Cipher.ENCRYPT_MODE, aes, GCMParameterSpec(128, iv))
                doFinal(text.toByteArray(Charsets.UTF_8))
            }
        return ByteBuffer
            .allocate(3 + wrapped.size + iv.size + body.size)
            .put(VERSION)
            .putShort(wrapped.size.toShort())
            .put(wrapped)
            .put(iv)
            .put(body)
            .array()
    }

    fun sealB64(
        publicKeyB64: String?,
        text: String,
    ): String? = publicKeyB64?.takeIf { it.isNotBlank() }?.let { Base64.getEncoder().encodeToString(seal(it, text)) }
}
