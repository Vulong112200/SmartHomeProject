package com.example.frontend

import android.appwidget.AppWidgetManager
import android.content.Context
import android.content.SharedPreferences
import android.net.Uri
import android.view.View
import android.widget.RemoteViews
import es.antonborri.home_widget.HomeWidgetBackgroundIntent
import es.antonborri.home_widget.HomeWidgetLaunchIntent
import es.antonborri.home_widget.HomeWidgetProvider

/**
 * App Widget hiển thị trạng thái sống của các thiết bị + nút điều khiển chạy nền.
 * Dữ liệu do Flutter đẩy sang qua home_widget (SharedPreferences "HomeWidgetPreferences").
 * Mỗi khe (p=máy lọc, c=cửa, f=máy cho ăn) đọc theo tiền tố khoá tương ứng.
 */
class SmartHomeWidgetProvider : HomeWidgetProvider() {

    override fun onUpdate(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetIds: IntArray,
        widgetData: SharedPreferences
    ) {
        appWidgetIds.forEach { widgetId ->
            val views = RemoteViews(context.packageName, R.layout.smart_home_widget).apply {
                // Bấm tiêu đề → mở app.
                setOnClickPendingIntent(
                    R.id.widget_title,
                    HomeWidgetLaunchIntent.getActivity(context, MainActivity::class.java)
                )
                // Nút làm mới → chạy nền fetch lại toàn bộ trạng thái.
                setOnClickPendingIntent(
                    R.id.btn_refresh,
                    HomeWidgetBackgroundIntent.getBroadcast(context, Uri.parse("smarthome://refresh"))
                )

                bindSlot(context, this, widgetData, "p", R.id.row_p, R.id.p_name, R.id.p_status, R.id.p_btn)
                bindSlot(context, this, widgetData, "c", R.id.row_c, R.id.c_name, R.id.c_status, R.id.c_btn)
                bindSlot(context, this, widgetData, "f", R.id.row_f, R.id.f_name, R.id.f_status, R.id.f_btn)
            }
            appWidgetManager.updateAppWidget(widgetId, views)
        }
    }

    private fun bindSlot(
        context: Context,
        views: RemoteViews,
        data: SharedPreferences,
        slot: String,
        rowId: Int,
        nameId: Int,
        statusId: Int,
        btnId: Int
    ) {
        val visible = data.getString("${slot}_visible", "0") == "1"
        if (!visible) {
            views.setViewVisibility(rowId, View.GONE)
            return
        }
        views.setViewVisibility(rowId, View.VISIBLE)
        views.setTextViewText(nameId, data.getString("${slot}_name", "") ?: "")
        views.setTextViewText(statusId, data.getString("${slot}_status", "—") ?: "—")

        val type = Uri.encode(data.getString("${slot}_type", "") ?: "")
        val brand = Uri.encode(data.getString("${slot}_brand", "") ?: "")
        val id = Uri.encode(data.getString("${slot}_id", "") ?: "")
        val uri = Uri.parse("smarthome://action?type=$type&brand=$brand&id=$id")
        views.setOnClickPendingIntent(
            btnId,
            HomeWidgetBackgroundIntent.getBroadcast(context, uri)
        )
    }
}
