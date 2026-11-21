package sn.seetlu.shopphone.service

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import sn.seetlu.shopphone.App
import sn.seetlu.shopphone.core.Uploader
import java.util.concurrent.TimeUnit

/** Every 15 min, and right after a capture when online (docs/08). Also refreshes the parser rules. */
class UploadWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val app = applicationContext as App
        val token = app.store.token ?: return Result.success()
        runCatching { app.api.parsers(token, app.store.rulesEtag) }.getOrNull()?.let { (json, etag) ->
            app.setRules(json)
            app.store.rulesEtag = etag
            ParserKey.extract(json)?.let { app.store.publicKey = it }
        }
        return when (app.uploader.run()) {
            is Uploader.Outcome.Done, Uploader.Outcome.NotPaired -> Result.success()
            is Uploader.Outcome.RetryLater -> Result.retry()
        }
    }

    companion object {
        private val online = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

        fun schedule(context: Context) {
            val req = PeriodicWorkRequestBuilder<UploadWorker>(15, TimeUnit.MINUTES).setConstraints(online).build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork("upload", ExistingPeriodicWorkPolicy.KEEP, req)
        }

        fun now(context: Context) {
            val req =
                OneTimeWorkRequestBuilder<UploadWorker>()
                    .setConstraints(online)
                    .build()
            WorkManager.getInstance(context).enqueueUniqueWork("upload-now", ExistingWorkPolicy.REPLACE, req)
        }
    }
}

internal object ParserKey {
    fun extract(json: String): String? =
        runCatching {
            sn.seetlu.shopphone.core.ParserEngine
                .fromJson(json)
                .rules.rawPublicKeyB64
        }.getOrNull()
}
