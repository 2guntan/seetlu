package sn.seetlu.shopphone.service

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import sn.seetlu.shopphone.App
import sn.seetlu.shopphone.core.Capture
import java.time.Instant

/** Reads notifications of the packages named in the parser rules only; everything else is skipped unread. */
class PaymentListenerService : NotificationListenerService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val app = application as App
        val engine = app.engine() ?: return
        if (sbn.packageName !in engine.packages) return
        val extras = sbn.notification.extras
        val text =
            listOfNotNull(
                extras.getCharSequence(Notification.EXTRA_TITLE),
                extras.getCharSequence(Notification.EXTRA_BIG_TEXT) ?: extras.getCharSequence(Notification.EXTRA_TEXT),
            ).joinToString("\n")
        if (text.isBlank()) return
        scope.launch {
            val outcome = app.capture.onNotification(sbn.packageName, text, Instant.ofEpochMilli(sbn.postTime))
            if (outcome == Capture.Outcome.SALE || outcome == Capture.Outcome.UNPARSED) UploadWorker.now(app)
        }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }
}
