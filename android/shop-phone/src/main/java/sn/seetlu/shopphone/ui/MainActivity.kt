package sn.seetlu.shopphone.ui

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.GridLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import sn.seetlu.shopphone.App
import sn.seetlu.shopphone.R
import sn.seetlu.shopphone.core.PendingSale
import sn.seetlu.shopphone.service.UploadWorker
import java.time.Instant
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

/** Quick-log pad: big amount pad, Enregistrer, last 10 entries, day total (docs/08). */
class MainActivity : AppCompatActivity() {
    private var amount = ""
    private lateinit var app: App

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        app = application as App
        if (app.store.token == null) {
            startActivity(Intent(this, PairActivity::class.java))
            finish()
            return
        }
        setContentView(R.layout.activity_main)
        findViewById<TextView>(R.id.shop_name).text = app.store.shopName
        val pad = findViewById<GridLayout>(R.id.pad)
        for (key in listOf("1", "2", "3", "4", "5", "6", "7", "8", "9", "000", "0", "⌫")) {
            val b = layoutInflater.inflate(R.layout.pad_key, pad, false) as Button
            b.text = key
            b.setOnClickListener { press(key) }
            pad.addView(b)
        }
        findViewById<Button>(R.id.save).setOnClickListener { save() }
        findViewById<Button>(R.id.health).setOnClickListener { startActivity(Intent(this, HealthActivity::class.java)) }
        render()
    }

    override fun onResume() {
        super.onResume()
        if (::app.isInitialized && app.store.token != null) {
            findViewById<TextView>(R.id.access_banner).visibility =
                if (Permissions.listenerEnabled(this)) android.view.View.GONE else android.view.View.VISIBLE
            refreshList()
        }
    }

    private fun press(key: String) {
        amount =
            when (key) {
                "⌫" -> amount.dropLast(1)
                else -> (amount + key).trimStart('0').take(8)
            }
        render()
    }

    private fun save() {
        val value = amount.toLongOrNull() ?: return
        if (value <= 0) return
        lifecycleScope.launch {
            app.capture.quickLog(value, Instant.now())
            amount = ""
            render()
            refreshList()
            UploadWorker.now(app)
        }
    }

    private fun render() {
        findViewById<TextView>(R.id.amount).text = if (amount.isEmpty()) "0 F" else Money.format(amount.toLong())
        findViewById<Button>(R.id.save).isEnabled = amount.isNotEmpty()
    }

    private fun refreshList() {
        lifecycleScope.launch {
            val zone = ZoneId.of(app.store.timezone)
            val start = ZonedDateTime.now(zone).toLocalDate().atStartOfDay(zone).toInstant()
            val total = app.queue.totalSince("quick_log", start)
            val last = app.queue.recent("quick_log", 10)
            findViewById<TextView>(R.id.total).text = getString(R.string.day_total, Money.format(total))
            findViewById<TextView>(R.id.recent).text = last.joinToString("\n") { line(it, zone) }
        }
    }

    private fun line(
        s: PendingSale,
        zone: ZoneId,
    ): String {
        val t = DateTimeFormatter.ofPattern("HH:mm").withZone(zone).format(s.occurredAt)
        val mark = if (s.uploaded) "✓" else "…"
        return "$t   ${Money.format(s.amountXof)}   $mark"
    }
}
