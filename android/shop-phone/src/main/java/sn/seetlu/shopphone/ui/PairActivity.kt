package sn.seetlu.shopphone.ui

import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import sn.seetlu.shopphone.App
import sn.seetlu.shopphone.R
import sn.seetlu.shopphone.core.ApiException
import sn.seetlu.shopphone.service.UploadWorker

/** Pairing: the owner app shows a 6-digit code; the token is stored encrypted on the phone. */
class PairActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val app = application as App
        if (app.store.token != null) {
            startActivity(Intent(this, MainActivity::class.java))
            finish()
            return
        }
        setContentView(R.layout.activity_pair)
        val code = findViewById<EditText>(R.id.pair_code)
        val error = findViewById<TextView>(R.id.pair_error)
        val button = findViewById<Button>(R.id.pair_button)
        button.setOnClickListener {
            val value = code.text.toString().filter { it.isDigit() }
            if (value.length != 6) {
                error.setText(R.string.pair_code_format)
                return@setOnClickListener
            }
            button.isEnabled = false
            lifecycleScope.launch {
                val result =
                    withContext(Dispatchers.IO) {
                        runCatching {
                            val r = app.api.pair(value, "${Build.MANUFACTURER} ${Build.MODEL}")
                            app.store.token = r.deviceToken
                            app.store.shopName = r.shopName
                            app.store.timezone = r.timezone
                            app.store.publicKey = r.rawPublicKeyB64
                            app.api.parsers(r.deviceToken, null)?.let { (json, etag) ->
                                app.setRules(json)
                                app.store.rulesEtag = etag
                            }
                        }
                    }
                button.isEnabled = true
                result
                    .onSuccess {
                        UploadWorker.schedule(app)
                        startActivity(Intent(this@PairActivity, MainActivity::class.java))
                        finish()
                    }.onFailure { e ->
                        error.setText(if (e is ApiException && e.status == 404) R.string.pair_bad_code else R.string.network_error)
                    }
            }
        }
    }
}
