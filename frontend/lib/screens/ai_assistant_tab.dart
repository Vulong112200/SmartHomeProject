import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'package:http/http.dart' as http;
import 'package:flutter_animate/flutter_animate.dart';

import '../core/websocket_provider.dart';
import '../theme/app_colors.dart';
import 'chat_bubble.dart';

class AIAssistantTab extends ConsumerStatefulWidget {
  const AIAssistantTab({super.key});

  @override
  ConsumerState<AIAssistantTab> createState() => _AIAssistantTabState();
}

class _AIAssistantTabState extends ConsumerState<AIAssistantTab> {
  final TextEditingController _commandController = TextEditingController();
  final ScrollController _scrollCtrl = ScrollController();
  final stt.SpeechToText _speech = stt.SpeechToText();
  
  bool _isListening = false;
  bool _isTyping = false;
  bool _hasGreetedThisSession = false;
  final String baseUrl = 'https://vuhp-smarthome.onrender.com';

  List<Map<String, dynamic>> messages = [
    {"isUser": false, "text": "Chào Vũ! Tôi là trợ lý AI. Bạn muốn điều khiển thiết bị nào?", "actions": []}
  ];

  void _scrollToBottom() {
    Future.delayed(const Duration(milliseconds: 100), () {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.animateTo(_scrollCtrl.position.maxScrollExtent, duration: const Duration(milliseconds: 300), curve: Curves.easeOut);
      }
    });
  }

  void _listen() async {
    if (!_isListening) {
      bool available = await _speech.initialize(
        onStatus: (status) {
          // Nếu engine tự ngắt do im lặng, ta chốt gửi lệnh luôn
          if (status == 'notListening' && _isListening) {
            setState(() => _isListening = false);
            _sendCommand();
          }
        },
      );

      if (available) {
        _hasGreetedThisSession = false;
        setState(() => _isListening = true);

        _speech.listen(
          onResult: (val) {
            // Chuyển về lowercase và trim để so sánh chính xác hơn
            String currentWords = val.recognizedWords.toLowerCase().trim();

            // 1. Wake word "Tom có nghe không"
            if (currentWords.contains("tom có nghe không") && !_hasGreetedThisSession) {
              _hasGreetedThisSession = true;
              setState(() {
                messages.add({"isUser": false, "text": "Tom đang nghe đây 🎙️", "actions": []});
                _scrollToBottom();
              });
            }

            // 2. CẢI TIẾN NHẬN DIỆN "OVER" (Thêm các biến thể tiếng Việt)
            // Đôi khi AI nghe "over" thành "ô vờ", "ô vơ" hoặc "ok"
            bool detectedOver = currentWords.endsWith("over") || 
                               currentWords.endsWith("ô vờ") || 
                               currentWords.endsWith("ô vơ");

            if (detectedOver) {
              _speech.stop(); // Ngắt mic ngay lập tức
              setState(() {
                _isListening = false;
                // Xóa từ khóa kết thúc khỏi nội dung gửi đi
                _commandController.text = val.recognizedWords
                    .replaceAll(RegExp(r'(?i)over|ô vờ|ô vơ'), '')
                    .trim();
              });
              
              // Gửi lệnh ngay lập tức, không delay 1ms nào
              _sendCommand(); 
              return;
            }

            setState(() {
              _commandController.text = val.recognizedWords;
              // Nếu engine báo đã kết thúc câu nói (theo pauseFor)
              if (val.finalResult) {
                setState(() => _isListening = false);
                _sendCommand();
              }
            });
          },
          localeId: 'vi_VN',
          // --- THAY ĐỔI QUAN TRỌNG: GIẢM THỜI GIAN NGẮT ---
          // Chỉ chờ 1.5 giây im lặng là engine sẽ tự động chốt finalResult
          pauseFor: const Duration(milliseconds: 4500), 
          listenMode: stt.ListenMode.deviceDefault,
          partialResults: true, // Đảm bảo nhận diện liên tục để bắt chữ "over" kịp thời
        );
      }
    } else {
      setState(() => _isListening = false);
      _speech.stop();
    }
  }

  void _sendCommand() async {
    final text = _commandController.text.trim();
    if (text.isEmpty) return;

    setState(() {
      messages.add({"isUser": true, "text": text, "actions": []});
      _isTyping = true;
      _commandController.clear();
    });
    _scrollToBottom();
    
    ref.read(webSocketProvider.notifier).sendMessage("Bạn: $text");

    try {
      final response = await http.post(
        Uri.parse('$baseUrl/api/ai/parse'),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode({"text": text}),
      );
      
      if (response.statusCode == 200) {
        final resData = jsonDecode(utf8.decode(response.bodyBytes));
        
        setState(() {
          _isTyping = false;
          List parsedActions = resData['execution_results'] ?? [];
          
          if (parsedActions.isEmpty) {
            messages.add({"isUser": false, "text": "Tôi chưa hiểu lệnh này, bạn có thể nói rõ hơn không?", "actions": []});
          } else {
            messages.add({
              "isUser": false, 
              "text": "Đã thực hiện xong lệnh của bạn:",
              "actions": parsedActions
            });
          }
        });
        _scrollToBottom();
      }
    } catch (e) {
      setState(() {
        _isTyping = false;
        messages.add({"isUser": false, "text": "Lỗi mất kết nối với máy chủ AI.", "actions": []});
      });
      _scrollToBottom();
    }
  }

  @override
  Widget build(BuildContext context) {
    final wsState = ref.watch(webSocketProvider);
    final wsNotifier = ref.read(webSocketProvider.notifier);

    return Column(
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Row(
                children: [
                  Icon(Icons.auto_awesome, color: AppColors.primary),
                  SizedBox(width: 8),
                  Text("Trợ lý Smart Home", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                ],
              ),
              GestureDetector(
                onTap: () {
                  if (!wsState.isConnected) wsNotifier.connect();
                },
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(
                    color: wsState.isConnected ? AppColors.success.withValues(alpha: 0.1) : Colors.redAccent.withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(color: wsState.isConnected ? AppColors.success : Colors.redAccent),
                  ),
                  child: Row(
                    children: [
                      Icon(Icons.circle, size: 8, color: wsState.isConnected ? AppColors.success : Colors.redAccent),
                      const SizedBox(width: 6),
                      Text(wsState.isConnected ? "Live" : "Mất kết nối", style: const TextStyle(fontSize: 12)),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
        
        Expanded(
          child: ListView.builder(
            controller: _scrollCtrl,
            padding: const EdgeInsets.symmetric(horizontal: 16),
            itemCount: messages.length + (_isTyping ? 1 : 0),
            itemBuilder: (context, index) {
              if (index == messages.length && _isTyping) {
                return const TypingIndicator();
              }
              return ChatBubble(message: messages[index])
                  .animate().fade().slideY(begin: 0.1, duration: 300.ms);
            },
          ),
        ),

        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: AppColors.surface,
            border: Border(top: BorderSide(color: Colors.white.withValues(alpha: 0.05))),
          ),
          child: SafeArea(
            child: Row(
              children: [
                GestureDetector(
                  onTap: _listen,
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 300),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: _isListening ? AppColors.success.withValues(alpha: 0.2) : AppColors.cardLight,
                      border: Border.all(color: _isListening ? AppColors.success : Colors.transparent),
                    ),
                    child: Icon(_isListening ? Icons.stop : Icons.mic_none, color: _isListening ? AppColors.success : AppColors.textMain),
                  ).animate(target: _isListening ? 1 : 0).shimmer(duration: 1.seconds, color: AppColors.success),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: TextField(
                    controller: _commandController,
                    style: const TextStyle(color: AppColors.textMain),
                    decoration: InputDecoration(
                      hintText: _isListening ? "Đang nghe..." : "Nhập lệnh hoặc đọc...",
                      hintStyle: const TextStyle(color: AppColors.textSub),
                      filled: true,
                      fillColor: AppColors.card,
                      contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(30), borderSide: BorderSide.none),
                    ),
                    onSubmitted: (_) => _sendCommand(),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton(
                  icon: const Icon(Icons.send_rounded, color: AppColors.primary),
                  onPressed: _sendCommand,
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}