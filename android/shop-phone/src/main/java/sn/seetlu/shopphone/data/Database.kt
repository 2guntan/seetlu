package sn.seetlu.shopphone.data

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import sn.seetlu.shopphone.core.PendingSale
import sn.seetlu.shopphone.core.PendingUnparsed
import sn.seetlu.shopphone.core.SaleQueue
import java.time.Instant
import java.time.temporal.ChronoUnit

@Entity(tableName = "sales")
data class SaleEntity(
    @PrimaryKey val clientId: String,
    val source: String,
    val amountXof: Long,
    val occurredAtMs: Long,
    val externalRef: String?,
    val rawB64: String?,
    val parserVersion: String?,
    val uploaded: Boolean,
)

@Entity(tableName = "unparsed")
data class UnparsedEntity(
    @PrimaryKey val id: String,
    val packageName: String,
    val receivedAtMs: Long,
    val rawB64: String,
    val uploaded: Boolean,
)

@Dao
interface QueueDao {
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertSale(e: SaleEntity)

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertUnparsed(e: UnparsedEntity)

    @Query("SELECT COUNT(*) FROM sales WHERE source = :source AND externalRef = :ref")
    suspend fun countRef(
        source: String,
        ref: String,
    ): Int

    @Query("SELECT * FROM sales WHERE uploaded = 0 ORDER BY clientId LIMIT :limit")
    suspend fun pendingSales(limit: Int): List<SaleEntity>

    @Query("SELECT * FROM unparsed WHERE uploaded = 0 ORDER BY id LIMIT :limit")
    suspend fun pendingUnparsed(limit: Int): List<UnparsedEntity>

    @Query("UPDATE sales SET uploaded = 1, rawB64 = NULL WHERE clientId IN (:ids)")
    suspend fun markSales(ids: List<String>)

    @Query("DELETE FROM unparsed WHERE id IN (:ids)")
    suspend fun deleteUnparsed(ids: List<String>)

    @Query("SELECT * FROM sales WHERE source = :source ORDER BY occurredAtMs DESC LIMIT :limit")
    suspend fun recent(
        source: String,
        limit: Int,
    ): List<SaleEntity>

    @Query("SELECT COALESCE(SUM(amountXof), 0) FROM sales WHERE source = :source AND occurredAtMs >= :sinceMs")
    suspend fun totalSince(
        source: String,
        sinceMs: Long,
    ): Long

    @Query("SELECT (SELECT COUNT(*) FROM sales WHERE uploaded = 0) + (SELECT COUNT(*) FROM unparsed WHERE uploaded = 0)")
    suspend fun pendingCount(): Int

    @Query("DELETE FROM sales WHERE uploaded = 1 AND occurredAtMs < :beforeMs")
    suspend fun prune(beforeMs: Long)
}

@Database(entities = [SaleEntity::class, UnparsedEntity::class], version = 1, exportSchema = true)
abstract class AppDatabase : RoomDatabase() {
    abstract fun queue(): QueueDao

    companion object {
        fun open(context: Context): AppDatabase = Room.databaseBuilder(context, AppDatabase::class.java, "seetlu.db").build()
    }
}

/** Room-backed queue. Uploaded sales drop their sealed raw text and are kept 7 days for the pad. */
class RoomSaleQueue(
    private val dao: QueueDao,
) : SaleQueue {
    override suspend fun addSale(sale: PendingSale) =
        dao.insertSale(
            SaleEntity(
                sale.clientId,
                sale.source,
                sale.amountXof,
                sale.occurredAt.toEpochMilli(),
                sale.externalRef,
                sale.rawB64,
                sale.parserVersion,
                false,
            ),
        )

    override suspend fun addUnparsed(item: PendingUnparsed) =
        dao.insertUnparsed(UnparsedEntity(item.id, item.packageName, item.receivedAt.toEpochMilli(), item.rawB64, false))

    override suspend fun hasRef(
        source: String,
        ref: String,
    ) = dao.countRef(source, ref) > 0

    override suspend fun pendingSales(limit: Int) = dao.pendingSales(limit).map { it.toPending() }

    override suspend fun pendingUnparsed(limit: Int) =
        dao.pendingUnparsed(limit).map { PendingUnparsed(it.id, it.packageName, Instant.ofEpochMilli(it.receivedAtMs), it.rawB64) }

    override suspend fun markUploaded(
        saleIds: List<String>,
        unparsedIds: List<String>,
    ) {
        if (saleIds.isNotEmpty()) dao.markSales(saleIds)
        if (unparsedIds.isNotEmpty()) dao.deleteUnparsed(unparsedIds)
        dao.prune(Instant.now().minus(7, ChronoUnit.DAYS).toEpochMilli())
    }

    override suspend fun recent(
        source: String,
        limit: Int,
    ) = dao.recent(source, limit).map { it.toPending() }

    override suspend fun totalSince(
        source: String,
        since: Instant,
    ) = dao.totalSince(source, since.toEpochMilli())

    override suspend fun pendingCount() = dao.pendingCount()

    private fun SaleEntity.toPending() =
        PendingSale(clientId, source, amountXof, Instant.ofEpochMilli(occurredAtMs), externalRef, rawB64, parserVersion, uploaded)
}
