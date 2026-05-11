// frontend/lib/main.dart
import 'dart:convert';
import 'package:speech_to_text/speech_to_text.dart' as stt;
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
  // THAY ĐỊA CHỈ IP NÀY BẰNG IP IPv4 CỦA MÁY TÍNH
  // final String serverIp = '192.168.1.62'; 
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
      debugPrint("Lỗi kết nối API: $e"); // ĐÃ SỬA print -> debugPrint
      setState(() => isLoading = false);
    }
  }

// Hàm tạo giao diện Nút bấm cho máy lọc
  Widget _buildModeButton(dynamic device, String label, String modeValue) {
    return ActionChip(
      label: Text(label, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold)),
      backgroundColor: Colors.blueAccent.withValues(alpha: 0.1),
      side: const BorderSide(color: Colors.blueAccent, width: 0.5),
      onPressed: () async {
        final brand = device['brand'].toString().toLowerCase();
        final deviceId = device['id'];
        try {
          final url = Uri.parse('$baseUrl/api/test-control/$brand/$deviceId/mode?mode=$modeValue');
          debugPrint("Đang gọi API: $url");
          // await http.get(url);
          
          final response = await http.get(url);
          
          if (response.statusCode == 200) {// Tùy chọn: Thể hiện thông báo nhỏ trên màn hình
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text('Đã chọn chế độ: $label'), duration: const Duration(seconds: 1)),
            );
          } else {
            debugPrint("Server báo lỗi: ${response.body}");
          }
        } catch (e) {
          debugPrint("Lỗi đổi chế độ: $e");
        }
      },
    );
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
                final name = device['name'].toString().toLowerCase();
                final brand = device['brand'].toString().toLowerCase();
                
                // Phân loại thiết bị
                bool isAirPurifier = name.contains('lọc');
                bool isFeeder = name.contains('mèo') || name.contains('ăn');
                bool isCurtain = name.contains('cửa');

                // Chọn Icon phù hợp
                IconData icon = Icons.device_hub;
                if (isFeeder) icon = Icons.pets;
                if (isCurtain) icon = Icons.blinds;
                if (isAirPurifier) icon = Icons.air;

                return Card(
                  color: Colors.white10,
                  margin: const EdgeInsets.only(bottom: 16),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                  child: Column(
                    children: [
                      ListTile(
                        contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
                        leading: CircleAvatar(
                          backgroundColor: device['is_active'] ? Colors.blueAccent.withValues(alpha: 0.2) : Colors.grey.withValues(alpha: 0.1),
                          child: Icon(icon, color: device['is_active'] ? Colors.blueAccent : Colors.grey),
                        ),
                        title: Text(device['name'], style: const TextStyle(fontWeight: FontWeight.bold)),
                        subtitle: Text("Hãng: ${device['brand']}"),
                        // Tắt Switch ON/OFF đối với máy cho mèo ăn vì nó chỉ có nút nhả hạt
                        trailing: isFeeder ? null : Switch(
                          value: device['is_active'],
                          onChanged: (bool value) async {
                            setState(() => device['is_active'] = value);
                            final action = value ? "on" : "off";
                            final dBrand = device['brand'];
                            final dId = device['id'];
                            try {
                              await http.get(Uri.parse('$baseUrl/api/test-control/$dBrand/$dId?action=$action'));
                            } catch (e) {
                              setState(() => device['is_active'] = !value);
                            }
                          },
                        ),
                      ),
                      
                      // 1. NÚT BẤM CHO MÁY LỌC KHÔNG KHÍ
                      if (isAirPurifier && device['is_active'])
                        Padding(
                          padding: const EdgeInsets.only(left: 16, right: 16, bottom: 16),
                          child: Wrap(
                            spacing: 8.0, runSpacing: 8.0, alignment: WrapAlignment.center,
                            children: [
                              _buildModeButton(device, 'Thấp', '1'),
                              _buildModeButton(device, 'Trung bình', '2'),
                              _buildModeButton(device, 'Cao', '3'),
                              _buildModeButton(device, 'Auto', 'auto'),
                              _buildModeButton(device, 'Ngủ', 'sleep'),
                            ],
                          ),
                        ),

                      // 2. NÚT BẤM CHO MÁY CHO MÈO ĂN (Luôn hiện)
                      if (isFeeder)
                        Padding(
                          padding: const EdgeInsets.only(left: 16, right: 16, bottom: 16),
                          child: Wrap(
                            spacing: 8.0, alignment: WrapAlignment.center,
                            children: [
                              _buildModeButton(device, 'Nhả 1 phần', '1'),
                              _buildModeButton(device, 'Nhả 2 phần', '2'),
                              _buildModeButton(device, 'Nhả 3 phần', '3'),
                            ],
                          ),
                        ),

                      // 3. NÚT BẤM CHO CỬA CUỐN
                      if (isCurtain)
                        Padding(
                          padding: const EdgeInsets.only(left: 16, right: 16, bottom: 16),
                          child: Wrap(
                            spacing: 8.0, alignment: WrapAlignment.center,
                            children: [
                              _buildModeButton(device, 'Mở cửa', 'open'),
                              _buildModeButton(device, 'Dừng', 'stop'),
                              _buildModeButton(device, 'Đóng cửa', 'close'),
                            ],
                          ),
                        ),
                    ],
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
class _AiTabState extends State<AiTab> {
  stt.SpeechToText _speech = stt.SpeechToText();
  bool _isListening = false;
  String _text = "Bấm mic và nói lệnh của bạn...";

  void _listen() async {
    if (!_isListening) {
      bool available = await _speech.initialize();
      if (available) {
        setState(() => _isListening = true);
        _speech.listen(
          onResult: (val) => setState(() {
            _text = val.recognizedWords;
            if (val.finalResult) {
              _isListening = false;
              _sendToAI(_text); // Gửi chữ về Cloud khi nói xong
            }
          }),
          localeId: 'vi_VN', // Bắt tiếng Việt
        );
      }
    } else {
      setState(() => _isListening = false);
      _speech.stop();
    }
  }

  // Hàm gửi lệnh lên Server AI
  Future<void> _sendToAI(String command) async {
     // Gọi API POST /api/ai/parse mà chúng ta sẽ viết ở Bước 3
     final response = await http.post(
       Uri.parse('$baseUrl/api/ai/parse'),
       headers: {"Content-Type": "application/json"},
       body: jsonEncode({"text": command}),
     );
     // Hiển thị phản hồi của AI lên màn hình...
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Expanded(child: Center(child: Text(_text))),
        FloatingActionButton(
          onPressed: _listen,
          child: Icon(_isListening ? Icons.mic : Icons.mic_none),
          backgroundColor: _isListening ? Colors.red : Colors.blue,
        ),
      ],
    );
  }
}

class AIAssistantTab extends ConsumerStatefulWidget {
  const AIAssistantTab({super.key});

  @override
  ConsumerState<AIAssistantTab> createState() => _AIAssistantTabState();
}

class _AIAssistantTabState extends ConsumerState<AIAssistantTab> {
  final TextEditingController _commandController = TextEditingController();

  void _sendCommand() {
    final text = _commandController.text.trim();
    if (text.isNotEmpty) {
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