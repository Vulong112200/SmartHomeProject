package com.example.frontend

import android.content.Intent
import androidx.core.content.pm.ShortcutInfoCompat
import androidx.core.content.pm.ShortcutManagerCompat
import androidx.core.graphics.drawable.IconCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {

    private val channelName = "smarthome/shortcuts"
    private var channel: MethodChannel? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        channel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
        channel?.setMethodCallHandler { call, result ->
            when (call.method) {
                "isPinSupported" -> {
                    result.success(ShortcutManagerCompat.isRequestPinShortcutSupported(this))
                }
                "pinShortcut" -> {
                    try {
                        val shortcut = buildShortcut(call.arguments as Map<*, *>)
                        if (ShortcutManagerCompat.isRequestPinShortcutSupported(this)) {
                            val ok = ShortcutManagerCompat.requestPinShortcut(this, shortcut, null)
                            result.success(ok)
                        } else {
                            result.success(false)
                        }
                    } catch (e: Exception) {
                        result.error("PIN_ERROR", e.message, null)
                    }
                }
                "updateShortcut" -> {
                    try {
                        val shortcut = buildShortcut(call.arguments as Map<*, *>)
                        // updateShortcuts cập nhật cả shortcut động lẫn shortcut đã pin.
                        val ok = ShortcutManagerCompat.updateShortcuts(this, listOf(shortcut))
                        result.success(ok)
                    } catch (e: Exception) {
                        result.error("UPDATE_ERROR", e.message, null)
                    }
                }
                "getInitialAction" -> {
                    result.success(actionFromIntent(intent))
                }
                else -> result.notImplemented()
            }
        }
    }

    override fun onNewIntent(newIntent: Intent) {
        super.onNewIntent(newIntent)
        setIntent(newIntent)
        val map = actionFromIntent(newIntent)
        if (map != null) channel?.invokeMethod("onShortcutAction", map)
    }

    // Dựng ShortcutInfoCompat từ tham số Dart gửi sang.
    private fun buildShortcut(args: Map<*, *>): ShortcutInfoCompat {
        val id = args["id"] as String
        val shortLabel = (args["shortLabel"] as? String) ?: "Shortcut"
        val longLabel = (args["longLabel"] as? String) ?: shortLabel
        val iconRes = (args["iconRes"] as? String) ?: "launcher_icon"

        val intent = Intent(this, MainActivity::class.java).apply {
            action = Intent.ACTION_VIEW
            addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)
            putExtra("type", args["type"] as? String)
            putExtra("brand", args["brand"] as? String)
            putExtra("deviceId", args["deviceId"] as? String)
            putExtra("deviceName", args["deviceName"] as? String)
        }

        return ShortcutInfoCompat.Builder(this, id)
            .setShortLabel(shortLabel)
            .setLongLabel(longLabel)
            .setIcon(resolveIcon(iconRes))
            .setIntent(intent)
            .build()
    }

    // Tìm drawable/mipmap theo tên; fallback về launcher_icon rồi icon mặc định.
    private fun resolveIcon(name: String): IconCompat {
        var resId = resources.getIdentifier(name, "drawable", packageName)
        if (resId == 0) resId = resources.getIdentifier(name, "mipmap", packageName)
        if (resId == 0) resId = resources.getIdentifier("launcher_icon", "mipmap", packageName)
        if (resId == 0) resId = applicationInfo.icon
        return IconCompat.createWithResource(this, resId)
    }

    // Đọc payload shortcut từ intent; trả null nếu intent không phải từ shortcut.
    private fun actionFromIntent(source: Intent?): HashMap<String, String?>? {
        if (source == null) return null
        val type = source.getStringExtra("type") ?: return null
        return hashMapOf(
            "type" to type,
            "brand" to source.getStringExtra("brand"),
            "deviceId" to source.getStringExtra("deviceId"),
            "deviceName" to source.getStringExtra("deviceName")
        )
    }
}
