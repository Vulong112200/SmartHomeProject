import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

// Import các file bạn vừa tạo
import 'theme/app_theme.dart';
import 'theme/app_colors.dart';
import 'screens/dashboard_tab.dart';
import 'screens/ai_assistant_tab.dart';
import 'screens/schedule_tab.dart';
import 'core/shortcut_handler.dart';
import 'core/widget_service.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
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
    return MaterialApp(
      title: 'Smart Home Premium',
      debugShowCheckedModeBanner: false,
      navigatorKey: appNavigatorKey, // Cho phép shortcut hiện dialog/snackbar
      theme: AppTheme.darkTheme, // Áp dụng theme mới
      home: const MainScreen(),
    );
  }
}

class MainScreen extends StatefulWidget {
  const MainScreen({super.key});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> {
  int _currentIndex = 0;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      // Hiển thị nội dung dựa theo tab đang chọn.
      // isVisible cho DashboardTab biết tab Home có đang hiển thị không —
      // để tạm dừng poll trạng thái 6s khi người dùng ở tab khác (tiết kiệm pin/mạng).
      body: IndexedStack(
        index: _currentIndex,
        children: [
          DashboardTab(isVisible: _currentIndex == 0),
          const AIAssistantTab(),
          const ScheduleTab(),
        ],
      ),

      // Thanh điều hướng hiện đại
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: (index) => setState(() => _currentIndex = index),
        backgroundColor: AppColors.surface,
        indicatorColor: AppColors.primary.withValues(alpha: 0.2), // Fix chuẩn Flutter 3.27+
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.dashboard_outlined),
            selectedIcon: Icon(Icons.dashboard, color: AppColors.primary),
            label: 'Home',
          ),
          NavigationDestination(
            icon: Icon(Icons.auto_awesome_outlined),
            selectedIcon: Icon(Icons.auto_awesome, color: AppColors.primary),
            label: 'AI Assistant',
          ),
          NavigationDestination(
            icon: Icon(Icons.schedule_outlined),
            selectedIcon: Icon(Icons.schedule, color: AppColors.primary),
            label: 'Hẹn giờ',
          ),
        ],
      ),
    );
  }
}