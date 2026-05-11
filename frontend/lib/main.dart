import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;
import 'package:speech_to_text/speech_to_text.dart' as stt; // Thêm thư viện voice
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
          DevicesTab(),      // Tab 0: Thiết bị
          AIAssistantTab(),  // Tab 1: Trợ lý AI (Đã hợp nhất)
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
// TAB 1: DANH SÁCH THIẾT BỊ (GIỮ NGUYÊN LOGIC CỦA VŨ)
// ==========================================
class DevicesTab extends StatefulWidget {
  const DevicesTab({super.key});

  @override
  State<DevicesTab> createState() => _DevicesTabState();
}

class _DevicesTabState extends State<DevicesTab> {
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

  Widget _buildModeButton(dynamic device, String label, String modeValue) {
    return ActionChip(
      label: Text(label, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold)),
      backgroundColor: Colors.blueAccent.withOpacity(0.1),
      side: const BorderSide(color: Colors.blueAccent, width: 0.5),
      onPressed: () async {
        final brand = device['brand'].toString().toLowerCase();
        final deviceId = device['id'];
        try {
          final url = Uri.parse('$baseUrl/api/test-control/$brand/$deviceId/mode?mode=$modeValue');
          final response = await http.get(url);
          if (response.statusCode == 200) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text('Đã chọn: $label'), duration: const Duration(seconds: 1)),
            );
          }
        } catch (e) {
          debugPrint("Lỗi: $e");
        }
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Nhà của tôi', style: TextStyle(fontWeight: FontWeight.bold))),
      body: isLoading 
        ? const Center(child: CircularProgressIndicator())
        : ListView.builder(
            padding: const EdgeInsets.all(16),
            itemCount: devices.length,
            itemBuilder: (context, index) {
              final device = devices[index];
              final name = device['name'].toString().toLowerCase();
              bool isAirPurifier = name.contains('lọc');
              bool isFeeder = name.contains('mèo') || name.contains('ăn');
              bool isCurtain = name.contains('cửa');

              IconData icon = Icons.device_hub;
              if (isFeeder) icon = Icons.pets;
              if (isCurtain) icon = Icons.blinds;
              if (isAirPurifier) icon = Icons.air;

              return Card(
                color: Colors.white10,
                margin: const EdgeInsets.only(bottom: 16),
                child: Column(
                  children: [
                    ListTile(
                      leading: Icon(icon, color: device['is_active'] ? Colors.blueAccent : Colors.grey),
                      title: Text(device['name']),
                      subtitle: Text("Hãng: ${device['brand']}"),
                      trailing: isFeeder ? null : Switch(
                        value: device['is_active'],
                        onChanged: (val) async {
                          final action = val ? "on" : "off";
                          await http.get(Uri.parse('$baseUrl/api/test-control/${device['brand']}/${device['id']}?action=$action'));
                          setState(() => device['is_active'] = val);
                        },
                      ),
                    ),
                    if (isAirPurifier && device['is_active'])
                      Wrap(children: [_buildModeButton(device, 'Auto', 'auto'), _buildModeButton(device, 'Ngủ', 'sleep')]),
                    if (isFeeder)
                      Wrap(children: [_buildModeButton(device, 'Nhả 1 phần', '1'), _buildModeButton(device, 'Nhả 2 phần', '2')]),
                    if (isCurtain)
                      Wrap(children: [_buildModeButton(device, 'Mở', 'open'), _buildModeButton(device, 'Dừng', 'stop'), _buildModeButton(device, 'Đóng', 'close')]),
                  ],
                ),
              );
            },
          ),
    );
  }
}

// ==========================================
// TAB 2: TRỢ LÝ AI (HỢP NHẤT CHAT + VOICE)
// ==========================================
class AIAssistantTab extends ConsumerStatefulWidget {
  const AIAssistantTab({super.key});

  @override
  ConsumerState<AIAssistantTab> createState() => _AIAssistantTabState();
}

class _AIAssistantTabState extends ConsumerState<AIAssistantTab> {
  final TextEditingController _commandController = TextEditingController();
  final stt.SpeechToText _speech = stt.SpeechToText();
  bool _isListening = false;
  final String baseUrl = 'https://vuhp-smarthome.onrender.com';

  // Logic bắt giọng nói
  void _listen() async {
    if (!_isListening) {
      bool available = await _speech.initialize();
      if (available) {
        setState(() => _isListening = true);
        _speech.listen(
          onResult: (val) {
            setState(() {
              _commandController.text = val.recognizedWords;
              if (val.finalResult) {
                _isListening = false;
                _sendCommand(); // Tự động gửi khi nói xong
              }
            });
          },
          localeId: 'vi_VN',
        );
      }
    } else {
      setState(() => _isListening = false);
      _speech.stop();
    }
  }

  // Gửi lệnh (Cả từ text field và voice)
  void _sendCommand() async {
    final text = _commandController.text.trim();
    if (text.isEmpty) return;

    // 1. Hiện lệnh lên màn hình log (WebSocket)
    ref.read(webSocketProvider.notifier).sendMessage("Bạn: $text");
    _commandController.clear();

    // 2. Gửi lên Backend để Gemini xử lý
    try {
      final response = await http.post(
        Uri.parse('$baseUrl/api/ai/parse'),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode({"text": text}),
      );
      
      if (response.statusCode == 200) {
        final resData = jsonDecode(response.body);
        ref.read(webSocketProvider.notifier).sendMessage("AI: Đang thực thi lệnh...");
      }
    } catch (e) {
      ref.read(webSocketProvider.notifier).sendMessage("Lỗi AI: $e");
    }
  }

  @override
  Widget build(BuildContext context) {
    final wsState = ref.watch(webSocketProvider);
    final wsNotifier = ref.read(webSocketProvider.notifier);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Trợ lý Smart Home'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 20),
            child: Icon(Icons.circle, size: 14, color: wsState.isConnected ? Colors.greenAccent : Colors.redAccent),
          )
        ],
      ),
      body: Column(
        children: [
          if (!wsState.isConnected)
            ElevatedButton(onPressed: () => wsNotifier.connect(), child: const Text('Kết nối Server')),
          Expanded(
            child: Container(
              margin: const EdgeInsets.all(16),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: Colors.black45, borderRadius: BorderRadius.circular(16)),
              child: ListView.builder(
                itemCount: wsState.messages.length,
                itemBuilder: (context, index) => Text(
                  wsState.messages[index],
                  style: const TextStyle(color: Colors.greenAccent, fontFamily: 'monospace'),
                ),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16.0),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _commandController,
                    decoration: InputDecoration(
                      hintText: _isListening ? "Đang nghe..." : "Nhập lệnh hoặc bấm mic...",
                      filled: true,
                      fillColor: Colors.white10,
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(30), borderSide: BorderSide.none),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                // NÚT MIC
                CircleAvatar(
                  backgroundColor: _isListening ? Colors.red : Colors.white10,
                  child: IconButton(icon: Icon(_isListening ? Icons.stop : Icons.mic), onPressed: _listen),
                ),
                const SizedBox(width: 8),
                // NÚT SEND
                CircleAvatar(
                  backgroundColor: Colors.blueAccent,
                  child: IconButton(icon: const Icon(Icons.send), onPressed: _sendCommand),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}