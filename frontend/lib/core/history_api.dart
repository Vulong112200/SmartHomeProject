import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'auth_service.dart';
import 'config.dart';

/// Một dòng lịch sử: lệnh do hệ thống gửi, hoặc thay đổi quan sát được từ
/// bên ngoài (nút vật lý, app Smart Life...).
class HistoryEntry {
  final int id;
  final DateTime at; // giờ máy (local)
  final String deviceId;
  final String deviceName;
  final String actionLabel;
  final String source;
  final String? userName;
  /// null = sự kiện quan sát được (không phải lệnh của hệ thống, không có "thành công").
  final bool? success;
  final String? detail;

  const HistoryEntry({
    required this.id,
    required this.at,
    required this.deviceId,
    required this.deviceName,
    required this.actionLabel,
    required this.source,
    this.userName,
    this.success,
    this.detail,
  });

  int get atMs => at.millisecondsSinceEpoch;

  factory HistoryEntry.fromJson(Map<String, dynamic> j) => HistoryEntry(
        id: (j['id'] as num).toInt(),
        at: DateTime.fromMillisecondsSinceEpoch((j['at_ms'] as num).toInt()),
        deviceId: '${j['device_id'] ?? ''}',
        deviceName: '${j['device_name'] ?? j['device_id'] ?? '?'}',
        actionLabel: '${j['action_label'] ?? '?'}',
        source: '${j['source'] ?? ''}',
        userName: j['user_name'] as String?,
        success: j['success'] as bool?,
        detail: j['detail'] as String?,
      );

  /// Ai/cái gì gây ra: tên người cho lệnh trong app, nhãn nguồn cho phần còn lại.
  String get actor {
    if (userName != null && userName!.isNotEmpty) return userName!;
    return HistorySource.of(source).label;
  }
}

/// Nhãn + icon cho từng nguồn — nơi DUY NHẤT phía app định nghĩa danh sách
/// nguồn (khớp `command_logs.source` ở backend).
class HistorySource {
  final String label;
  final IconData icon;
  /// Thay đổi KHÔNG đến từ app này (nút vật lý, app hãng...).
  final bool outside;
  const HistorySource(this.label, this.icon, {this.outside = false});

  static const Map<String, HistorySource> all = {
    'app': HistorySource('App', Icons.touch_app_outlined),
    'widget': HistorySource('Widget', Icons.widgets_outlined),
    'shortcut': HistorySource('Icon nhanh', Icons.bolt_outlined),
    'voice': HistorySource('Giọng nói', Icons.mic_none),
    'scene': HistorySource('Kịch bản', Icons.auto_awesome_outlined),
    'schedule': HistorySource('Lịch hẹn', Icons.schedule),
    'tuya_app': HistorySource('App Smart Life', Icons.phone_android, outside: true),
    'device': HistorySource('Tại thiết bị', Icons.pan_tool_alt_outlined, outside: true),
    'external': HistorySource('Ngoài app', Icons.open_in_new, outside: true),
  };

  static HistorySource of(String key) =>
      all[key] ?? HistorySource(key.isEmpty ? '?' : key, Icons.help_outline);
}

class HistoryPage {
  final List<HistoryEntry> entries;
  final bool hasMore;
  const HistoryPage(this.entries, this.hasMore);
}

class HistoryApi {
  HistoryApi._();

  /// Lần tải đầu backend còn đọc nhật ký Tuya (tối đa ~10s) — dài hơn apiTimeout.
  static const Duration _timeout = Duration(seconds: 20);

  /// Trang lịch sử mới nhất trước. `beforeMs` = mốc của dòng cuối trang trước.
  /// Trả null nếu lỗi mạng/máy chủ.
  static Future<HistoryPage?> fetch({int limit = 50, int? beforeMs, String? deviceId}) async {
    final q = <String, String>{
      'limit': '$limit',
      if (beforeMs != null) 'before_ms': '$beforeMs',
      if (deviceId != null) 'device_id': deviceId,
      // Trang sau chỉ đọc DB: nhật ký ngoài đã kéo ở trang đầu.
      if (beforeMs != null) 'sync': 'false',
    };
    try {
      Map<String, String> headers;
      try {
        headers = await AuthService.headers();
      } on NotAuthenticatedException {
        headers = const {};
      }
      final res = await http
          .get(Uri.parse('${AppConfig.baseUrl}/api/history').replace(queryParameters: q), headers: headers)
          .timeout(_timeout);
      if (res.statusCode == 401) {
        AuthService.handleUnauthorized();
        return null;
      }
      if (res.statusCode != 200) return null;
      final body = json.decode(utf8.decode(res.bodyBytes));
      if (body['status'] != 'success') return null;
      final list = ((body['data'] as List?) ?? [])
          .map((e) => HistoryEntry.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();
      return HistoryPage(list, body['has_more'] == true);
    } catch (_) {
      return null;
    }
  }
}
