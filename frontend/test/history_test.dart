import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/core/history_api.dart';

void main() {
  Map<String, dynamic> row({String source = 'app', String? user = 'Long', bool? success = true}) => {
        'id': 1,
        'at_ms': DateTime(2026, 11, 5, 19, 9, 26).millisecondsSinceEpoch,
        'device_id': 'door',
        'device_name': 'Cửa cuốn',
        'action_label': 'Đóng',
        'source': source,
        'user_name': user,
        'success': success,
        'detail': null,
      };

  test('đọc đúng 1 dòng lịch sử', () {
    final e = HistoryEntry.fromJson(row());
    expect(e.deviceName, 'Cửa cuốn');
    expect(e.actionLabel, 'Đóng');
    expect(e.at, DateTime(2026, 11, 5, 19, 9, 26));
    expect(e.actor, 'Long');
    expect(e.success, isTrue);
  });

  test('không có người bấm thì hiện nguồn', () {
    expect(HistoryEntry.fromJson(row(source: 'device', user: null, success: null)).actor, 'Tại thiết bị');
    expect(HistoryEntry.fromJson(row(source: 'schedule', user: null)).actor, 'Lịch hẹn');
  });

  test('nguồn ngoài app được đánh dấu, nguồn lạ không làm sập', () {
    expect(HistorySource.of('device').outside, isTrue);
    expect(HistorySource.of('tuya_app').outside, isTrue);
    expect(HistorySource.of('widget').outside, isFalse);
    expect(HistorySource.of('nguon_moi').label, 'nguon_moi');
  });
}
