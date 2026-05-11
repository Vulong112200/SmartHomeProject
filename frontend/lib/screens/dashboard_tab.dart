import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:http/http.dart' as http;
import '../theme/app_colors.dart';

class DashboardTab extends StatefulWidget {
  const DashboardTab({super.key});

  @override
  State<DashboardTab> createState() => _DashboardTabState();
}

class _DashboardTabState extends State<DashboardTab> {
  final String baseUrl = 'https://vuhp-smarthome.onrender.com';
  List<dynamic> devices = [];
  bool isLoading = true;

  @override
  void initState() {
    super.initState();
    fetchDevices();
  }

  Future<void> fetchDevices() async {
    try {
      final response = await http.get(Uri.parse('$baseUrl/api/devices'));      
      if (response.statusCode == 200) {
        final data = json.decode(utf8.decode(response.bodyBytes));
        setState(() {
          devices = data['data'];
          isLoading = false;
        });
      }
    } catch (e) {
      debugPrint("Lỗi kết nối API: $e");
      setState(() => isLoading = false);
    }
  }

  Future<void> _toggleDeviceState(dynamic device, bool value) async {
    setState(() => device['is_active'] = value);
    final action = value ? "on" : "off";
    final brand = device['brand'];
    final dId = device['id'];
    try {
      await http.get(Uri.parse('$baseUrl/api/test-control/$brand/$dId?action=$action'));
    } catch (e) {
      setState(() => device['is_active'] = !value);
    }
  }

  @override
  Widget build(BuildContext context) {
    int activeCount = devices.where((d) => d['is_active'] == true).length;

    return SafeArea(
      child: isLoading 
      ? const Center(child: CircularProgressIndicator(color: AppColors.primary))
      : CustomScrollView(
        physics: const BouncingScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.all(24.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text("Welcome Home,", style: TextStyle(color: AppColors.textSub, fontSize: 14)),
                          Text("Vũ 🖖", style: TextStyle(color: AppColors.textMain, fontSize: 28, fontWeight: FontWeight.bold)),
                        ],
                      ),
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(16)),
                        child: const Icon(Icons.wb_sunny_rounded, color: Colors.orangeAccent),
                      ),
                    ],
                  ),
                  const SizedBox(height: 24),
                  Container(
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      gradient: AppColors.primaryGradient,
                      borderRadius: BorderRadius.circular(24),
                      boxShadow: [BoxShadow(color: AppColors.primary.withValues(alpha: 0.3), blurRadius: 20, offset: const Offset(0, 8))],
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        _buildStat("Nhiệt độ", "24°C", Icons.thermostat),
                        _buildStat("Độ ẩm", "60%", Icons.water_drop),
                        _buildStat("Đang bật", "$activeCount thiết bị", Icons.bolt),
                      ],
                    ),
                  ).animate().fade(duration: 500.ms).slideY(begin: 0.2),
                ],
              ),
            ),
          ),
          SliverList(
            delegate: SliverChildBuilderDelegate(
              (context, index) {
                return Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 8),
                  child: SmartDeviceCard(
                    device: devices[index],
                    baseUrl: baseUrl,
                    onToggle: (val) => _toggleDeviceState(devices[index], val),
                  ).animate().fade(delay: (100 * index).ms).slideX(begin: 0.1),
                );
              },
              childCount: devices.length,
            ),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: 100)),
        ],
      ),
    );
  }

  Widget _buildStat(String label, String value, IconData icon) {
    return Column(
      children: [
        Icon(icon, color: Colors.white70, size: 20),
        const SizedBox(height: 8),
        Text(value, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
        Text(label, style: const TextStyle(color: Colors.white70, fontSize: 12)),
      ],
    );
  }
}

class SmartDeviceCard extends StatelessWidget {
  final dynamic device;
  final String baseUrl;
  final Function(bool) onToggle;

  const SmartDeviceCard({super.key, required this.device, required this.baseUrl, required this.onToggle});

  Widget _buildModeButton(BuildContext context, String label, String modeValue, Color glowColor) {
    return ActionChip(
      label: Text(label, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: AppColors.textMain)),
      backgroundColor: AppColors.surface,
      side: BorderSide(color: glowColor.withValues(alpha: 0.3), width: 1),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      onPressed: () async {
        final brand = device['brand'].toString().toLowerCase();
        final deviceId = device['id'];
        try {
          final response = await http.get(Uri.parse('$baseUrl/api/test-control/$brand/$deviceId/mode?mode=$modeValue'));
          if (response.statusCode == 200) {
            
            // THÊM DÒNG NÀY ĐỂ FIX CẢNH BÁO BUILDCONTEXT:
            if (!context.mounted) return; 

            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text('Đã chọn: $label'), backgroundColor: glowColor, duration: const Duration(seconds: 1)),
            );
          }
        } catch (e) {
          debugPrint("Lỗi đổi chế độ: $e");
        }
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    bool isActive = device['is_active'];
    String originalName = device['name'];
    String nameLower = originalName.toLowerCase();
    
    bool isAirPurifier = nameLower.contains('lọc');
    bool isFeeder = nameLower.contains('mèo') || nameLower.contains('ăn');
    bool isCurtain = nameLower.contains('cửa');

    Color glowColor = AppColors.primary;
    IconData icon = Icons.device_hub;
    
    if (isAirPurifier) { glowColor = AppColors.cyan; icon = Icons.air; }
    if (isFeeder) { glowColor = AppColors.purple; icon = Icons.pets; }
    if (isCurtain) { glowColor = AppColors.success; icon = Icons.blinds; }

    bool showSwitch = !isFeeder && !isCurtain;

    return AnimatedContainer(
      duration: const Duration(milliseconds: 300),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: isActive ? glowColor.withValues(alpha: 0.5) : Colors.white10, width: 1.5),
        boxShadow: isActive
            ? [BoxShadow(color: glowColor.withValues(alpha: 0.15), blurRadius: 20, spreadRadius: 2)]
            : [],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: isActive ? glowColor.withValues(alpha: 0.2) : AppColors.surface,
                  shape: BoxShape.circle,
                ),
                child: Icon(icon, color: isActive ? glowColor : AppColors.textSub, size: 24),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(originalName, style: const TextStyle(color: AppColors.textMain, fontWeight: FontWeight.bold, fontSize: 16)),
                    Text(device['brand'].toString().toUpperCase(), style: const TextStyle(color: AppColors.textSub, fontSize: 12)),
                  ],
                ),
              ),
              if (showSwitch)
                Switch.adaptive(
                  value: isActive,
                  activeTrackColor: glowColor,
                  onChanged: onToggle,
                ),
            ],
          ),
          const SizedBox(height: 16),
          if (isAirPurifier)
            Wrap(
              spacing: 8.0, runSpacing: 8.0,
              children: [
                _buildModeButton(context, 'Thấp', '1', glowColor),
                _buildModeButton(context, 'TB', '2', glowColor),
                _buildModeButton(context, 'Cao', '3', glowColor),
                _buildModeButton(context, 'Auto', 'auto', glowColor),
                _buildModeButton(context, 'Sleep', 'sleep', glowColor),
              ],
            ),
          if (isFeeder)
            Wrap(
              spacing: 8.0, runSpacing: 8.0,
              children: [
                _buildModeButton(context, 'Nhả 1 phần', '1', glowColor),
                _buildModeButton(context, 'Nhả 2 phần', '2', glowColor),
                _buildModeButton(context, 'Nhả 3 phần', '3', glowColor),
              ],
            ),
          if (isCurtain)
            Wrap(
              spacing: 8.0, runSpacing: 8.0,
              children: [
                _buildModeButton(context, 'Mở cửa', 'open', glowColor),
                _buildModeButton(context, 'Dừng', 'stop', Colors.redAccent),
                _buildModeButton(context, 'Đóng cửa', 'close', glowColor),
              ],
            ),
        ],
      ),
    );
  }
}