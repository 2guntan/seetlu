package sn.seetlu.shopphone

import android.app.Application
import sn.seetlu.shopphone.core.ApiClient
import sn.seetlu.shopphone.core.Capture
import sn.seetlu.shopphone.core.ParserEngine
import sn.seetlu.shopphone.core.Uploader
import sn.seetlu.shopphone.data.AppDatabase
import sn.seetlu.shopphone.data.RoomSaleQueue
import sn.seetlu.shopphone.data.Store
import sn.seetlu.shopphone.service.UploadWorker

class App : Application() {
    lateinit var store: Store
        private set
    lateinit var queue: RoomSaleQueue
        private set
    lateinit var api: ApiClient
        private set
    lateinit var capture: Capture
        private set
    lateinit var uploader: Uploader
        private set

    @Volatile private var engine: ParserEngine? = null

    override fun onCreate() {
        super.onCreate()
        store = Store(this)
        queue = RoomSaleQueue(AppDatabase.open(this).queue())
        api = ApiClient(BuildConfig.API_BASE_URL, BuildConfig.VERSION_NAME)
        capture = Capture(queue, { engine() }, { store.publicKey })
        uploader =
            Uploader(queue, api, { store.token }, { store.unpair() }) { ok, at ->
                store.lastUploadOk = ok
                if (ok) store.lastUploadAtMs = at.toEpochMilli()
            }
        if (store.token != null) UploadWorker.schedule(this)
    }

    fun engine(): ParserEngine? {
        engine?.let { return it }
        val json = store.rulesJson ?: return null
        return runCatching { ParserEngine.fromJson(json) }.getOrNull()?.also { engine = it }
    }

    fun setRules(json: String) {
        engine = ParserEngine.fromJson(json)
        store.rulesJson = json
    }
}
