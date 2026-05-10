// frontend/lib/main.dart
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'core/websocket_provider.dart';

void main() {
  runApp(const ProviderScope(child: SmartHomeApp()));
}

class SmartHomeApp extends StatelessWidget {
  const SmartHomeApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Smart Home',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        colorSchemeSeed: Colors.blueAccent,
        scaffoldBackgroundColor: const Color(0xFF121212),
      ),
      home: const MainScreen(),
    );
  }
}

// Màn hình chính chứa thanh điều hướng (Bottom Nav)
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
      body: IndexedStack(
        index: _currentIndex,
        children: const [
          DevicesTab(), // Tab 0: Danh sách thiết bị
          AIAssistantTab(), // Tab 1: Trợ lý AI
        ],
      ),
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentIndex,
        onTap: (index) => setState(() => _currentIndex = index),
        backgroundColor: const Color(0xFF1E1E1E),
        selectedItemColor: Colors.blueAccent,
        unselectedItemColor: Colors.grey,
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.home), label: 'Thiết bị'),
          BottomNavigationBarItem(icon: Icon(Icons.mic), label: 'Trợ lý AI'),
        ],
      ),
    );
  }
}

// ==========================================
// TAB 1: DANH SÁCH THIẾT BỊ (LẤY TỪ DATABASE)
// ==========================================
class DevicesTab extends StatefulWidget {
  const DevicesTab({super.key});

  @override
  State<DevicesTab> createState() => _DevicesTabState();
}

class _DevicesTabState extends State<DevicesTab> {
  // THAY ĐỊA CHỈ IP NÀY BẰNG IP IPv4 CỦA MÁY TÍNH (MỞ TERMINAL GÕ ipconfig)
  final String serverIp = '192.168.1.62'; 
  
  List<dynamic> devices = [];
  bool isLoading = true;

  @override
  void initState() {
    super.initState();
    fetchDevices();
  }

  Future<void> fetchDevices() async {
    try {
      final response = await http.get(Uri.parse('http://$serverIp:8000/api/devices'));
      if (response.statusCode == 200) {
        final data = json.decode(utf8.decode(response.bodyBytes)); // Xử lý UTF-8 cho Web
        setState(() {
          devices = data['data'];
          isLoading = false;
        });
      }
    } catch (e) {
      print("Lỗi kết nối API: $e");
      setState(() => isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Nhà của tôi', style: TextStyle(fontWeight: FontWeight.bold)),
        backgroundColor: Colors.transparent,
      ),
      body: isLoading 
        ? const Center(child: CircularProgressIndicator())
        : devices.isEmpty 
          ? const Center(child: Text("Chưa có thiết bị nào"))
          : ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: devices.length,
              itemBuilder: (context, index) {
                final device = devices[index];
                IconData icon = Icons.device_hub;
                
                if (device['name'].toString().toLowerCase().contains('mèo')) icon = Icons.pets;
                if (device['name'].toString().toLowerCase().contains('lọc')) icon = Icons.air;
                if (device['name'].toString().toLowerCase().contains('cửa')) icon = Icons.door_sliding;

                return Card(
                  color: Colors.white10,
                  margin: const EdgeInsets.only(bottom: 16),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                  child: ListTile(
                    contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
                    leading: CircleAvatar(
                      backgroundColor: Colors.blueAccent.withOpacity(0.2),
                      child: Icon(icon, color: Colors.blueAccent),
                    ),
                    title: Text(device['name'], style: const TextStyle(fontWeight: FontWeight.bold)),
                    subtitle: Text("Hãng: ${device['brand']}"),
                    trailing: Switch(
                      value: device['is_active'],
                      onChanged: (bool value) async {
                        // 1. Cập nhật giao diện ngay lập tức cho mượt
                        setState(() => device['is_active'] = value);
                        
                        // 2. Gọi API điều khiển xuống Backend FastAPI
                        final action = value ? "on" : "off";
                        final brand = device['brand'];
                        final deviceId = device['id'];
                        
                        try {
                          final url = Uri.parse('http://$serverIp:8000/api/test-control/$brand/$deviceId?action=$action');
                          final response = await http.get(url);
                          
                          if (response.statusCode != 200) {
                            // Nếu lỗi, trả công tắc về trạng thái cũ
                            setState(() => device['is_active'] = !value);
                            print("Lỗi từ server: ${response.body}");
                          }
                        } catch (e) {
                          setState(() => device['is_active'] = !value);
                          print("Lỗi kết nối: $e");
                        }
                      },
                    ),
                  ),
                );
              },
            ),
    );
  }
}

// ==========================================
// TAB 2: TRỢ LÝ AI (KẾT NỐI WEBSOCKET)
// ==========================================
class AIAssistantTab extends ConsumerStatefulWidget {
  const AIAssistantTab({super.key});

  @override
  ConsumerState<AIAssistantTab> createState() => _AIAssistantTabState();
}

class _AIAssistantTabState extends ConsumerState<AIAssistantTab> {
  // Bộ điều khiển ô nhập văn bản (Giả lập Speech-to-Text)
  final TextEditingController _commandController = TextEditingController();

  void _sendCommand() {
    final text = _commandController.text.trim();
    if (text.isNotEmpty) {
      // Gửi văn bản lên Server qua WebSocket
      ref.read(webSocketProvider.notifier).sendMessage(text);
      _commandController.clear();
    }
  }

  @override
  void dispose() {
    _commandController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final wsState = ref.watch(webSocketProvider);
    final wsNotifier = ref.read(webSocketProvider.notifier);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Trợ lý Smart Home', style: TextStyle(fontWeight: FontWeight.bold)),
        centerTitle: true,
        backgroundColor: Colors.transparent,
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 20),
            child: Icon(
              Icons.circle,
              size: 14,
              color: wsState.isConnected ? Colors.greenAccent : Colors.redAccent,
            ),
          )
        ],
      ),
      body: Column(
        children: [
          const SizedBox(height: 20),
          if (!wsState.isConnected)
            ElevatedButton.icon(
              onPressed: () => wsNotifier.connect(),
              icon: const Icon(Icons.link),
              label: const Text('Kết nối Server'),
            ),
          Expanded(
            child: Container(
              margin: const EdgeInsets.all(16),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.black45,
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: Colors.white10),
              ),
              child: ListView.builder(
                itemCount: wsState.messages.length,
                itemBuilder: (context, index) {
                  return Padding(
                    padding: const EdgeInsets.only(bottom: 8.0),
                    child: Text(
                      wsState.messages[index],
                      style: const TextStyle(color: Colors.greenAccent, fontFamily: 'monospace', fontSize: 14),
                    ),
                  );
                },
              ),
            ),
          ),
          if (wsState.isConnected)
            Padding(
              padding: const EdgeInsets.all(16.0),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _commandController,
                      decoration: InputDecoration(
                        hintText: "Ví dụ: 'Bật đèn' hoặc 'Tắt quạt'...",
                        filled: true,
                        fillColor: Colors.white10,
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(30), borderSide: BorderSide.none),
                        contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
                      ),
                      onSubmitted: (_) => _sendCommand(),
                    ),
                  ),
                  const SizedBox(width: 12),
                  CircleAvatar(
                    radius: 25,
                    backgroundColor: Colors.blueAccent,
                    child: IconButton(icon: const Icon(Icons.send, color: Colors.white), onPressed: _sendCommand),
                  ),
                ],
              ),
            ),
          const SizedBox(height: 20),
        ],
      ),
    );
  }
}