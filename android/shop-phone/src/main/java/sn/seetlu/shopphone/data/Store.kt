package sn.seetlu.shopphone.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Device token and small state, in EncryptedSharedPreferences (docs/08). */
class Store(
    context: Context,
) {
    private val prefs: SharedPreferences =
        EncryptedSharedPreferences.create(
            context,
            "seetlu.secure",
            MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )

    var token: String?
        get() = prefs.getString("token", null)
        set(v) = prefs.edit().putString("token", v).apply()
    var shopName: String?
        get() = prefs.getString("shop_name", null)
        set(v) = prefs.edit().putString("shop_name", v).apply()
    var timezone: String
        get() = prefs.getString("timezone", null) ?: "Africa/Dakar"
        set(v) = prefs.edit().putString("timezone", v).apply()
    var publicKey: String?
        get() = prefs.getString("public_key", null)
        set(v) = prefs.edit().putString("public_key", v).apply()
    var rulesJson: String?
        get() = prefs.getString("rules_json", null)
        set(v) = prefs.edit().putString("rules_json", v).apply()
    var rulesEtag: String?
        get() = prefs.getString("rules_etag", null)
        set(v) = prefs.edit().putString("rules_etag", v).apply()
    var lastUploadAtMs: Long
        get() = prefs.getLong("last_upload_at", 0)
        set(v) = prefs.edit().putLong("last_upload_at", v).apply()
    var lastUploadOk: Boolean
        get() = prefs.getBoolean("last_upload_ok", false)
        set(v) = prefs.edit().putBoolean("last_upload_ok", v).apply()

    fun unpair() {
        prefs.edit().remove("token").remove("shop_name").apply()
    }
}
