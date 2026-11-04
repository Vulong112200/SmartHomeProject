// lib/widgets/chat_bubble.dart
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter/material.dart';
import '../theme/app_colors.dart';

class ChatBubble extends StatelessWidget {
  final Map<String, dynamic> message;

  const ChatBubble({super.key, required this.message});

  @override
  Widget build(BuildContext context) {
    bool isUser = message['isUser'];
    List actions = message['actions'] ?? [];

    return Padding(
      padding: const EdgeInsets.only(bottom: 24),
      child: Row(
        mainAxisAlignment: isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (!isUser) ...[
            CircleAvatar(backgroundColor: context.palette.cardLight, child: Icon(Icons.auto_awesome, color: context.palette.cyan, size: 18)),
            const SizedBox(width: 12),
          ],
          
          Flexible(
            child: Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                gradient: isUser ? context.palette.primaryGradient : null,
                color: isUser ? null : context.palette.card,
                borderRadius: BorderRadius.only(
                  topLeft: const Radius.circular(20),
                  topRight: const Radius.circular(20),
                  bottomLeft: Radius.circular(isUser ? 20 : 4),
                  bottomRight: Radius.circular(isUser ? 4 : 20),
                ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(message['text'], style: TextStyle(color: isUser ? Colors.white : context.palette.textMain, fontSize: 15, height: 1.4)),
                  
                  // BOX THỂ HIỆN HÀNH ĐỘNG CỦA AI ĐÃ THỰC THI (PARSED JSON)
                  if (!isUser && actions.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(color: context.palette.background, borderRadius: BorderRadius.circular(12), border: Border.all(color: context.palette.outline)),
                      child: Column(
                        children: actions.map((act) => Padding(
                          padding: const EdgeInsets.only(bottom: 8),
                          child: Row(
                            children: [
                              Icon(act['success'] ? Icons.check_circle : Icons.error, color: act['success'] ? context.palette.success : Colors.redAccent, size: 16),
                              const SizedBox(width: 8),
                              Expanded(child: Text("${act['device_name']} ➔ ${act['action']}", style: TextStyle(fontSize: 13, color: context.palette.textSub))),
                            ],
                          ),
                        )).toList(),
                      ),
                    ),
                  ]
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// Widget Loading Indicator khi AI đang suy nghĩ
class TypingIndicator extends StatelessWidget {
  const TypingIndicator({super.key});
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 24, left: 40),
      child: Text("AI đang xử lý...", style: TextStyle(color: context.palette.textSub, fontStyle: FontStyle.italic))
          .animate(onPlay: (controller) => controller.repeat())
          .shimmer(duration: 1.seconds, color: context.palette.cyan),
    );
  }
}