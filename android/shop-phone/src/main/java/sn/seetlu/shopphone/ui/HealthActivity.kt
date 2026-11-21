package sn.seetlu.shopphone.ui

import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import sn.seetlu.shopphone.App
import sn.seetlu.shopphone.R
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** Permission status, battery exemption, last upload, parser version (docs/08). */
class HealthActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_health)
        findViewById<Button>(R.id.open_listener_settings).setOnClickListener {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
        findViewById<Button>(R.id.open_battery_settings).setOnClickListener {
            startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }
    }

    override fun onResume() {
        super.onResume()
        val app = application as App
        val yes = getString(R.string.yes)
        val no = getString(R.string.no)
        findViewById<TextView>(R.id.listener_status).text =
            getString(R.string.health_listener, if (Permissions.listenerEnabled(this)) yes else no)
        findViewById<TextView>(R.id.battery_status).text =
            getString(R.string.health_battery, if (Permissions.batteryExempt(this)) yes else no)
        val at = app.store.lastUploadAtMs
        val zone = ZoneId.of(app.store.timezone)
        findViewById<TextView>(R.id.upload_status).text =
            if (at == 0L) {
                getString(R.string.health_never_uploaded)
            } else {
                getString(
                    R.string.health_last_upload,
                    DateTimeFormatter.ofPattern("dd/MM HH:mm").withZone(zone).format(Instant.ofEpochMilli(at)),
                )
            }
        findViewById<TextView>(R.id.parser_status).text =
            getString(R.string.health_parser, app.engine()?.rules?.version ?: "—")
        lifecycleScope.launch {
            findViewById<TextView>(R.id.pending_status).text = getString(R.string.health_pending, app.queue.pendingCount())
        }
    }
}
