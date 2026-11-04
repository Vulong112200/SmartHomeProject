package com.example.frontend

import android.app.PendingIntent
import android.content.Context
import android.net.Uri
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import es.antonborri.home_widget.HomeWidgetBackgroundIntent
import java.util.concurrent.TimeUnit

/**
 * Làm mới Home Widget định kỳ khi app ĐÓNG.
 *
 * `updatePeriodMillis` (30 phút) của AppWidget chỉ gọi onUpdate để VẼ LẠI dữ liệu
 * cũ trong SharedPreferences — không hề hỏi backend, nên trước đây widget giữ
 * trạng thái của lần cuối mở app (bấm công tắc tường / app khác không hiện lên).
 *
 * Worker này bắn đúng broadcast "smarthome://refresh" mà nút ↻ trên widget dùng
 * -> WidgetService.refreshAll ở isolate nền: CHỈ ĐỌC trạng thái, không gửi lệnh.
 * 15 phút là chu kỳ tối thiểu Android cho phép với PeriodicWork.
 */
class WidgetRefreshWorker(context: Context, params: WorkerParameters) : Worker(context, params) {

    override fun doWork(): Result = try {
        HomeWidgetBackgroundIntent.getBroadcast(applicationContext, Uri.parse("smarthome://refresh")).send()
        Result.success()
    } catch (e: PendingIntent.CanceledException) {
        Result.retry()
    }

    companion object {
        private const val WORK_NAME = "smarthome_widget_refresh"

        /** Idempotent (KEEP): gọi nhiều lần không tạo thêm job, không reset chu kỳ. */
        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<WidgetRefreshWorker>(15, TimeUnit.MINUTES)
                .setConstraints(
                    Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
                )
                .build()
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork(WORK_NAME, ExistingPeriodicWorkPolicy.KEEP, request)
        }

        fun cancel(context: Context) {
            WorkManager.getInstance(context).cancelUniqueWork(WORK_NAME)
        }
    }
}
