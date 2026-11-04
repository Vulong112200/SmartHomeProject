import 'package:flutter/material.dart';

import '../core/auth_service.dart';
import '../core/avatar.dart';
import '../core/household_api.dart';
import '../core/theme_controller.dart';
import '../core/voice_feedback.dart';
import '../theme/app_colors.dart';

/// Hồ sơ của CHÍNH MÌNH: tên hiển thị, màu avatar, giao diện sáng/tối.
///
/// Trả về hồ sơ đã sửa qua `Navigator.pop` để màn trước cập nhật lời chào /
/// avatar ngay, không phải gọi lại /api/me.
class ProfileScreen extends StatefulWidget {
  final HouseholdProfile profile;
  final Future<void> Function()? onSignOut;

  const ProfileScreen({super.key, required this.profile, this.onSignOut});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

const _roleLabel = {
  'owner': 'Chủ nhà',
  'adult': 'Người lớn',
  'kid': 'Trẻ em',
  'guest': 'Khách',
};

class _ProfileScreenState extends State<ProfileScreen> {
  late HouseholdProfile _profile = widget.profile;
  late final TextEditingController _name = TextEditingController(text: widget.profile.displayName);
  bool _saving = false;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  void _snack(String msg, {bool error = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(msg),
      backgroundColor: error ? Colors.redAccent : context.palette.primary,
      duration: const Duration(seconds: 2),
    ));
  }

  Future<void> _saveName() async {
    final name = _name.text.trim();
    if (name.isEmpty || name == _profile.displayName) return;
    setState(() => _saving = true);
    final err = await HouseholdApi.updateMe(displayName: name);
    if (!mounted) return;
    setState(() {
      _saving = false;
      if (err == null) _profile = _profile.copyWith(displayName: name);
    });
    _snack(err ?? 'Đã lưu tên.', error: err != null);
  }

  Future<void> _pickColor(String? hex) async {
    final err = hex == null
        ? await HouseholdApi.updateMe(clearAvatarColor: true)
        : await HouseholdApi.updateMe(avatarColor: hex);
    if (!mounted) return;
    if (err != null) {
      _snack(err, error: true);
      return;
    }
    setState(() => _profile = hex == null
        ? _profile.copyWith(clearAvatarColor: true)
        : _profile.copyWith(avatarColor: hex));
  }

  Widget _section(String title, Widget child) {
    final p = context.palette;
    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: p.card,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: p.outline),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: TextStyle(color: p.textSub, fontSize: 12, fontWeight: FontWeight.w600)),
          const SizedBox(height: 12),
          child,
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return PopScope(
      canPop: false,
      // Trả hồ sơ mới về màn trước (kể cả khi bấm nút back hệ thống).
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) Navigator.of(context).pop(_profile);
      },
      child: Scaffold(
        appBar: AppBar(title: const Text('Hồ sơ của tôi')),
        body: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            Center(child: UserAvatar(profile: _profile, size: 88)),
            const SizedBox(height: 12),
            Center(
              child: Text(
                _profile.friendlyName ?? 'Nhà mình',
                style: TextStyle(color: p.textMain, fontSize: 20, fontWeight: FontWeight.bold),
              ),
            ),
            Center(
              child: Text(
                '${_roleLabel[_profile.role] ?? _profile.role} • ${_profile.scopeLabel}',
                style: TextStyle(color: p.textSub, fontSize: 13),
                textAlign: TextAlign.center,
              ),
            ),
            if (_profile.email.isNotEmpty)
              Center(child: Text(_profile.email, style: TextStyle(color: p.textSub, fontSize: 12))),
            const SizedBox(height: 24),
            _section(
              'TÊN HIỂN THỊ',
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _name,
                      maxLength: 40,
                      style: TextStyle(color: p.textMain),
                      decoration: const InputDecoration(hintText: 'Tên cả nhà gọi bạn', counterText: ''),
                      onSubmitted: (_) => _saveName(),
                    ),
                  ),
                  const SizedBox(width: 8),
                  _saving
                      ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))
                      : IconButton(
                          tooltip: 'Lưu tên',
                          icon: Icon(Icons.check_circle, color: p.primary),
                          onPressed: _saveName,
                        ),
                ],
              ),
            ),
            _section(
              'MÀU AVATAR',
              Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  for (final hex in avatarColorChoices)
                    _ColorDot(
                      color: Color(int.parse('FF${hex.substring(1)}', radix: 16)),
                      selected: _profile.avatarColor?.toUpperCase() == hex,
                      onTap: () => _pickColor(hex),
                    ),
                  ActionChip(
                    label: const Text('Tự động'),
                    onPressed: _profile.avatarColor == null ? null : () => _pickColor(null),
                  ),
                ],
              ),
            ),
            _section(
              'GIAO DIỆN',
              ValueListenableBuilder<ThemeMode>(
                valueListenable: ThemeController.mode,
                builder: (context, mode, _) => SegmentedButton<ThemeMode>(
                  segments: [
                    for (final m in const [ThemeMode.system, ThemeMode.light, ThemeMode.dark])
                      ButtonSegment(value: m, label: Text(ThemeController.labels[m]!)),
                  ],
                  selected: {mode},
                  showSelectedIcon: false,
                  onSelectionChanged: (s) => ThemeController.set(s.first),
                ),
              ),
            ),
            _section(
              'TRỢ LÝ GIỌNG NÓI',
              ValueListenableBuilder<bool>(
                valueListenable: VoiceFeedback.enabled,
                // Row + Switch (không dùng SwitchListTile: khung có nền màu sẽ che hiệu ứng chạm của ListTile).
                builder: (context, on, _) => Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('Đọc to phản hồi', style: TextStyle(color: p.textMain)),
                          Text('"Đã tắt Máy bơm tăng áp"', style: TextStyle(color: p.textSub, fontSize: 12)),
                        ],
                      ),
                    ),
                    Switch.adaptive(value: on, onChanged: VoiceFeedback.setEnabled),
                  ],
                ),
              ),
            ),
            if (widget.onSignOut != null)
              TextButton.icon(
                onPressed: () async {
                  Navigator.of(context).pop(_profile);
                  await widget.onSignOut!.call();
                },
                icon: const Icon(Icons.logout, color: Colors.redAccent),
                label: const Text('Đăng xuất', style: TextStyle(color: Colors.redAccent)),
              ),
          ],
        ),
      ),
    );
  }
}

class _ColorDot extends StatelessWidget {
  final Color color;
  final bool selected;
  final VoidCallback onTap;

  const _ColorDot({required this.color, required this.selected, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 36,
        height: 36,
        decoration: BoxDecoration(
          color: color,
          shape: BoxShape.circle,
          border: Border.all(color: selected ? context.palette.textMain : Colors.transparent, width: 3),
        ),
        child: selected ? const Icon(Icons.check, color: Colors.white, size: 18) : null,
      ),
    );
  }
}
