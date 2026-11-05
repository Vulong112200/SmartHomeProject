import 'package:flutter/material.dart';

import '../core/auth_service.dart';
import '../theme/app_colors.dart';

/// Một mục hướng dẫn: tiêu đề + các dòng hướng dẫn.
class HelpTopic {
  final IconData icon;
  final String title;
  final List<String> steps;
  final bool adminOnly;
  const HelpTopic(this.icon, this.title, this.steps, {this.adminOnly = false});
}

/// Nội dung hướng dẫn — 1 chỗ duy nhất, dùng cho cả màn Hướng dẫn lẫn màn
/// giới thiệu lần đầu. Sửa tính năng thì sửa luôn ở đây.
const List<HelpTopic> helpTopics = [
  HelpTopic(Icons.touch_app_outlined, 'Điều khiển thiết bị', [
    'Tab Home hiện mọi thiết bị bạn được dùng, kèm trạng thái thật (tự cập nhật khi app đang mở).',
    'Máy lọc: bấm Thấp / TB / Cao / Auto / Sleep. Công tắc gạt để bật/tắt.',
    'Cửa cuốn: Mở / Dừng / Đóng. Máy bơm: gạt công tắc. Máy cho ăn: chọn số phần.',
    'Kéo biểu tượng ⋮⋮ bên phải thẻ để sắp xếp lại (chỉ khi đang xem "Tất cả").',
    'Kéo màn hình xuống để tải lại.',
  ]),
  HelpTopic(Icons.meeting_room_outlined, 'Nhà theo khu', [
    'Hàng chip phía trên lọc thiết bị theo khu, ví dụ "Phòng khách 1/3" = 1 trong 3 thiết bị đang bật.',
    'Khu có biểu tượng 🏠 là khu dùng chung: mọi người trong nhà đều dùng được.',
  ]),
  HelpTopic(Icons.auto_awesome_outlined, 'Kịch bản (1 nút, nhiều thiết bị)', [
    'Chạm thẻ kịch bản để chạy, ví dụ "Ra khỏi nhà" = đóng cửa + tắt máy lọc + tắt máy bơm.',
    'Kịch bản có MỞ CỬA sẽ hỏi xác nhận trước khi chạy.',
    'Chủ nhà / người lớn: bấm "+ Kịch bản" để tạo, giữ lâu thẻ để sửa hoặc xóa.',
  ]),
  HelpTopic(Icons.schedule_outlined, 'Hẹn giờ', [
    'Tab Hẹn giờ → nút + : chọn thiết bị, hành động, giờ và các ngày trong tuần.',
    'Chọn "Khoảng" để bật lúc này và tự tắt lúc khác (qua đêm được).',
    'Gạt công tắc trên thẻ lịch để tạm dừng / bật lại.',
  ]),
  HelpTopic(Icons.mic_none, 'Trợ lý giọng nói', [
    'Tab AI Assistant → bấm micro rồi nói. Ngừng nói 1,5 giây là lệnh được gửi.',
    'Ví dụ: "bật máy lọc mức cao", "tắt máy bơm", "đóng cửa cuốn", "cho mèo ăn 2 phần".',
    'Hẹn giờ bằng lời: "6 giờ sáng mai bật máy bơm", "từ 22 giờ đến 6 giờ bật máy lọc chế độ ngủ".',
    'Nói tên kịch bản để chạy nó: "ra khỏi nhà". Kịch bản có mở cửa phải chạy trên màn hình.',
    '"Tắt hết" chỉ tắt máy lọc và máy bơm — không đụng cửa và máy cho ăn.',
    'Trợ lý đọc to kết quả; tắt ở Hồ sơ → Trợ lý giọng nói.',
  ]),
  HelpTopic(Icons.widgets_outlined, 'Widget & icon nhanh ngoài màn hình chính', [
    'Giữ lâu màn hình chính điện thoại → Tiện ích (Widgets) → SmartHome Hub để thêm widget trạng thái.',
    'Widget tự làm mới khoảng 15 phút/lần khi app đóng; bấm ↻ để làm mới ngay.',
    'Trên thẻ thiết bị, bấm "Tạo icon xử lý nhanh" để có nút điều khiển ngay ngoài màn hình chính.',
  ]),
  HelpTopic(Icons.history, 'Lịch sử điều khiển', [
    'Bấm vào tên/ảnh của bạn ở góc trên → "Lịch sử điều khiển".',
    'Mỗi dòng cho biết thiết bị, lệnh, giờ, ai bấm và bấm từ đâu (app, widget, icon nhanh, giọng nói, kịch bản, lịch hẹn).',
    'Thao tác ngoài app cũng được ghi: "Tại thiết bị" = nút vật lý / công tắc tường / lịch cài trong máy; "App Smart Life" = bấm trong app của hãng.',
    'Máy lọc không khí chỉ phát hiện thay đổi ngoài app khi có người đang mở app, và giờ ghi là lúc phát hiện. Remote cửa cuốn không được ghi.',
    'Dòng có dấu ⚠ đỏ = thiết bị không nhận lệnh. Bật "Chỉ ngoài app" để xem riêng thao tác ngoài app.',
  ]),
  HelpTopic(Icons.person_outline, 'Hồ sơ, giao diện, mật khẩu', [
    'Bấm nút tài khoản góc trên → Hồ sơ & giao diện.',
    'Đổi tên hiển thị, màu avatar, giao diện Sáng / Tối / Theo hệ thống.',
    'Đổi mật khẩu ở mục Tài khoản. Quên mật khẩu: ở màn đăng nhập bấm "Quên mật khẩu?" để nhận mã qua email.',
  ]),
  HelpTopic(Icons.shield_outlined, 'Quyền theo vai', [
    'Chủ nhà: dùng mọi thiết bị + quản trị nhà (thành viên, khu vực, thiết bị).',
    'Người lớn: dùng mọi thiết bị, tạo kịch bản và hẹn giờ.',
    'Trẻ em: chỉ dùng thiết bị trong khu được cấp; sửa được lịch của chính mình.',
    'Khách: chỉ dùng thiết bị trong khu được cấp, không tạo lịch.',
  ]),
  HelpTopic(Icons.admin_panel_settings_outlined, 'Quản trị nhà (chủ nhà)', [
    'Người mới tự đăng ký trong app. Vào Quản trị nhà → Thành viên, tìm theo tên/email rồi bấm "Thêm vào nhà" và chọn vai, khu.',
    'Bấm vào một thành viên để đổi vai, cấp khu, đưa ra khỏi nhà hoặc chặn.',
    'Tab Khu vực: tạo khu, chuyển thiết bị giữa các khu, đặt loại thiết bị, bật "Dùng chung cả nhà".',
  ], adminOnly: true),
];

/// Hướng dẫn sử dụng đầy đủ (mở từ Hồ sơ → Hướng dẫn sử dụng).
class HelpScreen extends StatelessWidget {
  final HouseholdProfile profile;
  const HelpScreen({super.key, required this.profile});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final topics = helpTopics.where((t) => !t.adminOnly || profile.canAdmin).toList();
    return Scaffold(
      appBar: AppBar(title: const Text('Hướng dẫn sử dụng')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          for (final t in topics)
            Card(
              color: p.card,
              margin: const EdgeInsets.only(bottom: 10),
              child: ExpansionTile(
                leading: Icon(t.icon, color: p.primary),
                title: Text(t.title, style: TextStyle(color: p.textMain, fontWeight: FontWeight.w600)),
                childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                children: [
                  for (final s in t.steps)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('•  ', style: TextStyle(color: p.primary)),
                          Expanded(child: Text(s, style: TextStyle(color: p.textSub, height: 1.35))),
                        ],
                      ),
                    ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
