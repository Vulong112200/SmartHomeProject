import 'package:flutter/material.dart';

import 'auth_service.dart';

/// Bảng màu avatar cho người dùng chọn ở màn Hồ sơ (đủ đậm cho chữ trắng).
const List<String> avatarColorChoices = [
  '#4DA3FF', '#7B61FF', '#E0569B', '#F2784B',
  '#E5A50A', '#2BAE66', '#14A3A3', '#64748B',
];

Color _parseHex(String hex) => Color(int.parse('FF${hex.substring(1)}', radix: 16));

/// Màu avatar: màu tự chọn, hoặc suy ỔN ĐỊNH từ userId (cùng người luôn cùng màu).
Color avatarColorOf(HouseholdProfile p) {
  final chosen = p.avatarColor;
  if (chosen != null && RegExp(r'^#[0-9A-Fa-f]{6}$').hasMatch(chosen)) return _parseHex(chosen);
  final seed = p.userId.isNotEmpty ? p.userId : p.email;
  final hash = seed.codeUnits.fold<int>(0, (h, c) => (h * 31 + c) & 0x7fffffff);
  return _parseHex(avatarColorChoices[hash % avatarColorChoices.length]);
}

/// 1-2 chữ cái đầu của tên ("Hà Phi Vũ" -> "HV"); không có tên -> icon người.
String? initialsOf(HouseholdProfile p) {
  final name = p.friendlyName;
  if (name == null) return null;
  final words = name.split(RegExp(r'\s+')).where((w) => w.isNotEmpty).toList();
  if (words.isEmpty) return null;
  final first = words.first.characters.first;
  final last = words.length > 1 ? words.last.characters.first : '';
  return (first + last).toUpperCase();
}

class UserAvatar extends StatelessWidget {
  final HouseholdProfile profile;
  final double size;

  const UserAvatar({super.key, required this.profile, this.size = 40});

  @override
  Widget build(BuildContext context) {
    final initials = initialsOf(profile);
    return CircleAvatar(
      radius: size / 2,
      backgroundColor: avatarColorOf(profile),
      child: initials == null
          ? Icon(Icons.person, color: Colors.white, size: size * 0.55)
          : Text(
              initials,
              style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: size * 0.38),
            ),
    );
  }
}
