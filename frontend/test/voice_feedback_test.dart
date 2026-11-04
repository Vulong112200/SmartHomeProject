import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:frontend/core/voice_feedback.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('tóm tắt kết quả thành câu đọc tự nhiên', () {
    expect(
      VoiceFeedback.summarize([
        {'device_name': 'Máy bơm tăng áp', 'action': 'Tắt', 'success': true},
        {'device_name': 'Lọc không khí', 'action': 'Chế độ 3', 'success': true},
        {'device_name': 'Cửa cuốn', 'action': 'Không có quyền hoặc không tìm thấy thiết bị', 'success': false},
      ]),
      'Đã tắt Máy bơm tăng áp. Đã chuyển Lọc không khí sang chế độ 3. '
      'Cửa cuốn: Không có quyền hoặc không tìm thấy thiết bị',
    );
  });

  test('lịch hẹn đọc nguyên nhãn đã có chữ "Đã hẹn"', () {
    expect(
      VoiceFeedback.summarize([
        {'device_name': 'Máy bơm', 'action': 'Đã hẹn 06:00 • Bật', 'success': true},
      ]),
      'Máy bơm: Đã hẹn 06:00 • Bật',
    );
  });

  test('không có kết quả -> nói chưa hiểu; phần tử lạ bị bỏ qua', () {
    expect(VoiceFeedback.summarize([]), 'Tôi chưa hiểu lệnh này.');
    expect(VoiceFeedback.summarize([null, 3, {'device_name': 'Đèn', 'action': 'Bật', 'success': true}]), 'Đã bật Đèn');
  });

  test('bật/tắt đọc phản hồi được lưu, mặc định bật', () async {
    await VoiceFeedback.load();
    expect(VoiceFeedback.enabled.value, isTrue);
    await VoiceFeedback.setEnabled(false);
    VoiceFeedback.enabled.value = true;
    await VoiceFeedback.load();
    expect(VoiceFeedback.enabled.value, isFalse);
  });
}
