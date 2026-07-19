import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'package:http/http.dart' as http;
import 'package:flutter_animate/flutter_animate.dart';

import '../core/config.dart';
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

  Timer? _silenceTimer;
  bool _commandSentThisSession = false;

  final String baseUrl = AppConfig.baseUrl;

  List<Map<String, dynamic>> messages = [
    {"isUser": false, "text": "Chào Vũ! Tôi là trợ lý AI. Bạn muốn điều khiển thiết bị nào?", "actions": []}
  ];

  @override
  void initState() {
    super.initState();
    // Tự kết nối WebSocket khi vào app (trước đây phải bấm badge mới connect).
    Future.microtask(() => ref.read(webSocketProvider.notifier).connect());
  }

  @override
  void dispose() {
    // Giải phóng tài nguyên: controller/timer/mic — trước đây bị leak
    // (speech có thể giữ session mic nếu không stop).
    _silenceTimer?.cancel();
    _speech.stop();
    _commandController.dispose();
    _scrollCtrl.dispose();
    super.dispose();
  }

  void _executeSend() {
    if (_commandSentThisSession) return; // Nếu đã gửi rồi -> Bỏ qua ngay
    _commandSentThisSession = true;      // Đánh dấu là đã gửi
    
    setState(() => _isListening = false);
    _silenceTimer?.cancel();             // Tắt bộ đếm giờ
    _sendCommand();                      // Gọi hàm gửi lệnh của bạn
  }
  
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
          // Bỏ hàm gửi tự động ở đây để tránh bị duplicate lệnh
          if (status == 'notListening' && _isListening) {
            setState(() => _isListening = false);
            _silenceTimer?.cancel();
          }
        },
      );

      if (available) {
        // RESET CÁC BIẾN KHI BẮT ĐẦU NGHE MỚI
        _hasGreetedThisSession = false;
        _commandSentThisSession = false; 
        setState(() => _isListening = true);

        _speech.listen(
          onResult: (val) {
            String currentWords = val.recognizedWords.toLowerCase().trim();

            // 1. Wake word "Tom có nghe không"
            if (currentWords.contains("tom có nghe không") && !_hasGreetedThisSession) {
              _hasGreetedThisSession = true;
              setState(() {
                messages.add({"isUser": false, "text": "Tom đang nghe đây 🎙️", "actions": []});
                _scrollToBottom();
              });
            }

            // 2. Chốt bằng từ khóa "over"
            bool detectedOver = currentWords.endsWith("over") || 
                               currentWords.endsWith("ô vờ") || 
                               currentWords.endsWith("ô vơ");
            if (detectedOver) {
              _speech.stop();
              setState(() {
                _commandController.text = val.recognizedWords
                .replaceAll(RegExp(r'over|ô vờ|ô vơ', caseSensitive: false), '').trim();
              });
              _executeSend(); // GỌI HÀM CHỐT CHẶN
              return;
            }

            // --- LÕI ĐẾM THỜI GIAN IM LẶNG THỰC SỰ ---
            // Cứ mỗi lần bạn nói 1 từ mới, nó hủy giờ cũ và đếm lại 1.5s từ đầu
            setState(() => _commandController.text = val.recognizedWords);
            
            _silenceTimer?.cancel();
            _silenceTimer = Timer(const Duration(milliseconds: 1500), () {
              // Nếu bạn im lặng đúng 1.5s sau từ cuối cùng -> Tự động chốt
              if (_isListening) {
                _speech.stop();
                _executeSend(); // GỌI HÀM CHỐT CHẶN
              }
            });

            // 3. Fallback của hệ thống
            if (val.finalResult) {
              _executeSend(); // GỌI HÀM CHỐT CHẶN
            }
          },
          localeId: 'vi_VN',
          listenOptions: stt.SpeechListenOptions(partialResults: true, cancelOnError: true),
          // Đã XÓA pauseFor cũ để dùng Timer nội bộ siêu chuẩn xác ở trên
        );
      }
    } else {
      // Khi người dùng tự bấm nút Tắt Mic
      _silenceTimer?.cancel();
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
      final response = await http
          .post(
            Uri.parse('$baseUrl/api/ai/parse'),
            headers: {"Content-Type": "application/json"},
            body: jsonEncode({"text": text}),
          )
          .timeout(const Duration(seconds: 30)); // AI + IoT có thể chậm, nhưng không treo vô hạn

      if (!mounted) return;
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
      } else {
        // FIX: trước đây non-200 không có nhánh else -> _isTyping kẹt true,
        // indicator quay mãi. Giờ báo lỗi rõ ràng.
        setState(() {
          _isTyping = false;
          messages.add({"isUser": false, "text": "Máy chủ gặp lỗi (HTTP ${response.statusCode}). Thử lại sau nhé.", "actions": []});
        });
        _scrollToBottom();
      }
    } catch (e) {
      if (!mounted) return;
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
              const Expanded( // <--- BỌC EXPANDED Ở ĐÂY
                child: Row(
                  children: [
                    Icon(Icons.auto_awesome, color: AppColors.primary),
                    SizedBox(width: 8),
                    // Thêm Flexible và TextOverflow để chống tràn chữ
                    Flexible(
                      child: Text(
                        "Trợ lý Smart Home", 
                        style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
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