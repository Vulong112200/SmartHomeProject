import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

// Import các file bạn vừa tạo
import 'theme/app_theme.dart';
import 'theme/app_colors.dart';
import 'screens/dashboard_tab.dart';
import 'screens/ai_assistant_tab.dart';
import 'screens/schedule_tab.dart';
import 'screens/floor_plan/floor_plan_tab.dart';
import 'core/auth_service.dart';
import 'core/config.dart';
import 'core/realtime_service.dart';
import 'core/shortcut_handler.dart';
import 'core/theme_controller.dart';
import 'core/voice_feedback.dart';
import 'core/widget_service.dart';
import 'screens/auth_gate.dart';
import 'screens/onboarding_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Khởi tạo Supabase TRƯỚC runApp để session đã lưu kịp resolve — nếu không,
  // AuthGate sẽ nháy màn đăng nhập ở lần mở app đầu tiên.
  // Chưa cấu hình khóa thì bỏ qua: app chạy y như trước khi có đăng nhập.
  if (AppConfig.authEnabled) {
    try {
      await AuthService.init();
    } catch (e) {
      debugPrint('Không khởi tạo được Supabase: $e');
    }
  }

  // Đọc sáng/tối đã chọn TRƯỚC runApp để không nháy theme sai lúc mở app.
  await ThemeController.load();
  await VoiceFeedback.load();

  runApp(const ProviderScope(child: SmartHomeApp()));
  // Lắng nghe khi người dùng bấm icon shortcut trên home screen.
  ShortcutHandler.register();
  // Đăng ký Home Screen Widget (callback nền + nạp trạng thái lần đầu).
  WidgetService.init();
}

class SmartHomeApp extends StatelessWidget {
  const SmartHomeApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<ThemeMode>(
      valueListenable: ThemeController.mode,
      builder: (context, themeMode, _) => MaterialApp(
        title: 'Smart Home Premium',
        debugShowCheckedModeBanner: false,
        navigatorKey: appNavigatorKey, // Cho phép shortcut hiện dialog/snackbar
        theme: AppTheme.lightTheme,
        darkTheme: AppTheme.darkTheme,
        themeMode: themeMode,
        // Icon thanh trạng thái theo nền: app không dùng AppBar nên phải tự đặt,
        // không thì nền sáng mà icon trắng -> mất giờ/pin.
        builder: (context, child) => AnnotatedRegion<SystemUiOverlayStyle>(
          value: Theme.of(context).brightness == Brightness.dark
              ? SystemUiOverlayStyle.light
              : SystemUiOverlayStyle.dark,
          child: child!,
        ),
        // AuthGate quyết định: đang tải / chưa đăng nhập / chờ duyệt / mất mạng
        // / vào app. Hồ sơ được truyền xuống để không màn nào phải fetch lại.
        home: AuthGate(builder: (profile) => MainScreen(profile: profile)),
      ),
    );
  }
}

class MainScreen extends StatefulWidget {
  final HouseholdProfile profile;
  const MainScreen({super.key, required this.profile});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> with WidgetsBindingObserver {
  int _currentIndex = 0;
  // Bản hồ sơ đang dùng: sửa ở màn Hồ sơ thì cập nhật ở đây để lời chào /
  // avatar đổi ngay, không phải gọi lại /api/me.
  late HouseholdProfile _profile = widget.profile;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // Trạng thái thời gian thực: MainScreen chỉ tồn tại khi AuthGate đã vào
    // app (đã đăng nhập + được duyệt) ⇒ không bao giờ nối khi chưa có quyền.
    RealtimeService.instance.start();
    // Giới thiệu nhanh ở lần đầu vào app (sau frame đầu để có Navigator).
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) OnboardingScreen.showIfFirstTime(context);
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // App vào nền ⇒ đóng /ws (máy chủ ngừng đọc thiết bị khi không ai nghe);
    // quay lại ⇒ nối ngay, các thẻ tự đồng bộ lại. `inactive` (kéo thanh thông
    // báo) chỉ thoáng qua nên giữ nguyên.
    if (state == AppLifecycleState.resumed) {
      RealtimeService.instance.start();
    } else if (state == AppLifecycleState.paused || state == AppLifecycleState.detached) {
      RealtimeService.instance.stop();
    }
  }

  @override
  void dispose() {
    // Đăng xuất ⇒ AuthGate gỡ MainScreen ⇒ đóng kết nối của tài khoản cũ.
    WidgetsBinding.instance.removeObserver(this);
    RealtimeService.instance.stop();
    super.dispose();
  }

  Future<void> _signOut() async {
    await AuthService.signOut();
    // AuthGate lắng nghe onAuthStateChange nên tự chuyển về màn đăng nhập.
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      // Hiển thị nội dung dựa theo tab đang chọn.
      // isVisible cho DashboardTab biết tab Home có đang hiển thị không —
      // để tạm dừng poll trạng thái 6s khi người dùng ở tab khác (tiết kiệm pin/mạng).
      body: IndexedStack(
        index: _currentIndex,
        children: [
          DashboardTab(
            isVisible: _currentIndex == 0,
            profile: _profile,
            onProfileChanged: (p) => setState(() => _profile = p),
            // Chỉ hiện nút Đăng xuất khi thật sự có đăng nhập; bản build chưa
            // cấu hình Supabase thì nút đó không làm được gì.
            onSignOut: AppConfig.authEnabled ? _signOut : null,
          ),
          // Sơ đồ mặt bằng 2D: tách riêng khỏi Dashboard; chỉ tải lần đầu khi
          // được mở và chỉ poll trạng thái khi đang hiển thị.
          FloorPlanTab(isVisible: _currentIndex == 1, profile: _profile),
          AIAssistantTab(profile: _profile),
          const ScheduleTab(),
        ],
      ),

      // Thanh điều hướng hiện đại
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: (index) => setState(() => _currentIndex = index),
        backgroundColor: context.palette.surface,
        indicatorColor: context.palette.primary.withValues(alpha: 0.2), // Fix chuẩn Flutter 3.27+
        destinations: [
          NavigationDestination(
            icon: const Icon(Icons.dashboard_outlined),
            selectedIcon: Icon(Icons.dashboard, color: context.palette.primary),
            label: 'Home',
          ),
          NavigationDestination(
            icon: const Icon(Icons.map_outlined),
            selectedIcon: Icon(Icons.map, color: context.palette.primary),
            label: 'Sơ đồ',
          ),
          NavigationDestination(
            icon: const Icon(Icons.auto_awesome_outlined),
            selectedIcon: Icon(Icons.auto_awesome, color: context.palette.primary),
            label: 'AI Assistant',
          ),
          NavigationDestination(
            icon: const Icon(Icons.schedule_outlined),
            selectedIcon: Icon(Icons.schedule, color: context.palette.primary),
            label: 'Hẹn giờ',
          ),
        ],
      ),
    );
  }
}