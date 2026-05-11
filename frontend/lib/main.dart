import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

// Import các file bạn vừa tạo
import 'theme/app_theme.dart';
import 'theme/app_colors.dart';
import 'screens/dashboard_tab.dart';
import 'screens/ai_assistant_tab.dart';

void main() {
  runApp(const ProviderScope(child: SmartHomeApp()));
}

class SmartHomeApp extends StatelessWidget {
  const SmartHomeApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Smart Home Premium',
      debugShowCheckedModeBanner: false,
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

  // Tạm thời dùng Mock Data để test UI (Sau này bạn map với Riverpod/API sau)
  final List<dynamic> _mockDevices = [
    {"id": "den_01", "name": "Đèn phòng khách", "brand": "tuya", "is_active": true},
    {"id": "loc_01", "name": "Máy lọc không khí", "brand": "vesync", "is_active": false},
    {"id": "meo_01", "name": "Máy cho mèo ăn", "brand": "rojeco", "is_active": true},
  ];

  void _toggleDevice(String id, bool val) {
    setState(() {
      final device = _mockDevices.firstWhere((d) => d['id'] == id);
      device['is_active'] = val;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      // Hiển thị nội dung dựa theo tab đang chọn
      body: IndexedStack(
        index: _currentIndex,
        children: [
          const DashboardTab(),
          const AIAssistantTab(),
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
        ],
      ),
    );
  }
}