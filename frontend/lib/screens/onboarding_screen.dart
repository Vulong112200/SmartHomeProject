import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../theme/app_colors.dart';

/// Giới thiệu nhanh ở LẦN ĐẦU vào app (lưu cờ theo máy). Hướng dẫn đầy đủ ở
/// Hồ sơ → Hướng dẫn sử dụng (help_screen.dart).
class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key});

  static const _key = 'onboarding_done_v1';

  /// Hiện màn giới thiệu nếu máy này chưa xem. Gọi sau khi vào màn chính.
  static Future<void> showIfFirstTime(BuildContext context) async {
    final prefs = await SharedPreferences.getInstance();
    if (prefs.getBool(_key) ?? false) return;
    if (!context.mounted) return;
    await Navigator.of(context).push(MaterialPageRoute(
      fullscreenDialog: true,
      builder: (_) => const OnboardingScreen(),
    ));
    await prefs.setBool(_key, true);
  }

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _Page {
  final IconData icon;
  final String title;
  final String body;
  const _Page(this.icon, this.title, this.body);
}

const _pages = [
  _Page(Icons.home_rounded, 'Chào mừng về nhà',
      'Điều khiển máy lọc, cửa cuốn, máy bơm, máy cho ăn ở cùng một nơi — trạng thái thật, cập nhật liên tục.'),
  _Page(Icons.meeting_room_outlined, 'Thiết bị theo khu',
      'Lọc thiết bị theo từng khu bằng hàng chip trên Home. Khu 🏠 là khu dùng chung của cả nhà.'),
  _Page(Icons.auto_awesome_outlined, 'Kịch bản & hẹn giờ',
      'Một chạm chạy nhiều thiết bị ("Ra khỏi nhà"). Tab Hẹn giờ để bật/tắt tự động theo giờ.'),
  _Page(Icons.mic_none, 'Ra lệnh bằng giọng nói',
      'Tab AI Assistant → bấm micro: "tắt máy bơm", "6 giờ sáng mai bật máy lọc", "ra khỏi nhà".'),
];

class _OnboardingScreenState extends State<OnboardingScreen> {
  final _ctrl = PageController();
  int _index = 0;

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final last = _index == _pages.length - 1;
    return Scaffold(
      backgroundColor: p.background,
      body: SafeArea(
        child: Column(
          children: [
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(onPressed: () => Navigator.pop(context), child: const Text('Bỏ qua')),
            ),
            Expanded(
              child: PageView(
                controller: _ctrl,
                onPageChanged: (i) => setState(() => _index = i),
                children: [
                  for (final pg in _pages)
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 32),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Container(
                            padding: const EdgeInsets.all(28),
                            decoration: BoxDecoration(color: p.primary.withValues(alpha: 0.12), shape: BoxShape.circle),
                            child: Icon(pg.icon, size: 64, color: p.primary),
                          ),
                          const SizedBox(height: 32),
                          Text(pg.title,
                              textAlign: TextAlign.center,
                              style: TextStyle(color: p.textMain, fontSize: 22, fontWeight: FontWeight.bold)),
                          const SizedBox(height: 12),
                          Text(pg.body,
                              textAlign: TextAlign.center,
                              style: TextStyle(color: p.textSub, fontSize: 15, height: 1.4)),
                        ],
                      ),
                    ),
                ],
              ),
            ),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                for (var i = 0; i < _pages.length; i++)
                  AnimatedContainer(
                    duration: const Duration(milliseconds: 200),
                    margin: const EdgeInsets.all(4),
                    width: i == _index ? 22 : 8,
                    height: 8,
                    decoration: BoxDecoration(
                      color: i == _index ? p.primary : p.outline,
                      borderRadius: BorderRadius.circular(4),
                    ),
                  ),
              ],
            ),
            Padding(
              padding: const EdgeInsets.all(24),
              child: SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: () => last
                      ? Navigator.pop(context)
                      : _ctrl.nextPage(duration: const Duration(milliseconds: 250), curve: Curves.easeOut),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    child: Text(last ? 'Bắt đầu' : 'Tiếp'),
                  ),
                ),
              ),
            ),
            Text('Xem lại bất cứ lúc nào: Hồ sơ → Hướng dẫn sử dụng',
                style: TextStyle(color: p.textSub, fontSize: 12)),
            const SizedBox(height: 12),
          ],
        ),
      ),
    );
  }
}
