package sn.seetlu.shopphone.ui

import android.content.ComponentName
import android.content.Context
import android.os.PowerManager
import android.provider.Settings
import sn.seetlu.shopphone.service.PaymentListenerService
import java.text.NumberFormat
import java.util.Locale

object Permissions {
    fun listenerEnabled(context: Context): Boolean {
        val flat = Settings.Secure.getString(context.contentResolver, "enabled_notification_listeners") ?: return false
        val me = ComponentName(context, PaymentListenerService::class.java).flattenToString()
        return flat.split(':').any { it == me }
    }

    fun batteryExempt(context: Context): Boolean =
        (context.getSystemService(Context.POWER_SERVICE) as PowerManager).isIgnoringBatteryOptimizations(context.packageName)
}

object Money {
    private val nf = NumberFormat.getIntegerInstance(Locale.FRANCE)

    fun format(xof: Long): String = "${nf.format(xof)} F"
}
