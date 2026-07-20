import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../core/device_api.dart';
import '../core/device_type.dart';
import '../core/schedule_api.dart';
import '../theme/app_colors.dart';

/// Nhãn ngày trong tuần theo weekday Python (0=Thứ2 … 6=CN) — khớp backend.
const List<String> _dayLabels = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'];

/// Một lựa chọn hành động trong form (hiển thị + giá trị gửi backend).
class _ActionOption {
  final String label;
  final String actionType;   // on | off | mode
  final String? actionValue; // đi kèm khi actionType == mode
  const _ActionOption(this.label, this.actionType, [this.actionValue]);

  String get key => '$actionType:${actionValue ?? ''}';
}

/// Danh sách hành động khả dụng theo loại thiết bị.
List<_ActionOption> _actionsFor(DeviceType type) {
  switch (type) {
    case DeviceType.airPurifier:
      return const [
        _ActionOption('Bật', 'on'),
        _ActionOption('Tắt', 'off'),
        _ActionOption('Lọc Thấp', 'mode', '1'),
        _ActionOption('Lọc TB', 'mode', '2'),
        _ActionOption('Lọc Cao', 'mode', '3'),
        _ActionOption('Lọc Auto', 'mode', 'auto'),
        _ActionOption('Lọc Ngủ', 'mode', 'sleep'),
      ];
    case DeviceType.curtain:
      return const [
        _ActionOption('Mở cửa', 'mode', 'open'),
        _ActionOption('Đóng cửa', 'mode', 'close'),
      ];
    case DeviceType.feeder:
      return const [
        _ActionOption('Nhả 1 phần', 'mode', '1'),
        _ActionOption('Nhả 2 phần', 'mode', '2'),
        _ActionOption('Nhả 3 phần', 'mode', '3'),
      ];
    case DeviceType.unknown:
      return const [
        _ActionOption('Bật', 'on'),
        _ActionOption('Tắt', 'off'),
      ];
  }
}

/// Nhãn tiếng Việt cho 1 hành động (dùng cho cả hành động bắt đầu lẫn kết thúc).
String _actionLabelFor(String actionType, String? actionValue, DeviceType type) {
  for (final opt in _actionsFor(type)) {
    if (opt.actionType == actionType && opt.actionValue == actionValue) {
      return opt.label;
    }
  }
  // Fallback khi loại thiết bị không xác định được từ tên.
  if (actionType == 'on') return 'Bật';
  if (actionType == 'off') return 'Tắt';
  return 'Chế độ ${actionValue ?? '?'}';
}

/// Nhãn tiếng Việt cho hành động của một lịch (hiện trên danh sách).
String _actionLabel(Schedule s, DeviceType type) =>
    _actionLabelFor(s.actionType, s.actionValue, type);

/// Mô tả hành động đầy đủ của lịch: đơn "Lọc Cao", khoảng "Lọc Cao → Lọc TB".
String _actionSummary(Schedule s, DeviceType type) {
  final start = _actionLabel(s, type);
  if (!s.isRange) return start;
  return '$start → ${_actionLabelFor(s.endActionType ?? '', s.endActionValue, type)}';
}

/// Nhãn ngày lặp: "Mỗi ngày" / "T2, T4, CN".
String _daysLabel(String days) {
  if (days.trim().isEmpty) return 'Mỗi ngày';
  final parts = days
      .split(',')
      .map((p) => int.tryParse(p.trim()))
      .whereType<int>()
      .where((d) => d >= 0 && d <= 6)
      .toList()
    ..sort();
  if (parts.length == 7) return 'Mỗi ngày';
  return parts.map((d) => _dayLabels[d]).join(', ');
}

class ScheduleTab extends StatefulWidget {
  const ScheduleTab({super.key});

  @override
  State<ScheduleTab> createState() => _ScheduleTabState();
}

class _ScheduleTabState extends State<ScheduleTab> {
  List<Schedule> _schedules = [];
  List<Map<String, dynamic>> _devices = [];
  bool _loading = true;
  bool _offline = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final results = await Future.wait([
      ScheduleApi.fetchSchedules(),
      DeviceApi.fetchDevices(),
    ]);
    if (!mounted) return;
    final schedules = results[0] as List<Schedule>?;
    final devices = results[1] as List<Map<String, dynamic>>?;
    setState(() {
      _loading = false;
      _offline = schedules == null;
      if (schedules != null) _schedules = schedules;
      if (devices != null) _devices = devices;
    });
  }

  Map<String, dynamic>? _deviceOf(Schedule s) {
    for (final d in _devices) {
      if ('${d['id']}' == s.deviceId) return d;
    }
    return null;
  }

  void _snack(String msg, {bool error = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(msg),
      backgroundColor: error ? Colors.redAccent : AppColors.primary,
      duration: const Duration(seconds: 2),
    ));
  }

  Future<void> _toggleEnabled(Schedule s, bool enabled) async {
    final err = await ScheduleApi.updateSchedule(s.id, {'enabled': enabled});
    if (err != null) {
      _snack(err, error: true);
    }
    _load();
  }

  Future<void> _delete(Schedule s) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.card,
        title: const Text('Xóa lịch?', style: TextStyle(color: AppColors.textMain)),
        content: Text(
          'Xóa lịch "${s.name.isNotEmpty ? s.name : '${s.time} • ${_actionLabel(s, _typeOf(s))}'}"?',
          style: const TextStyle(color: AppColors.textSub),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Hủy')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Xóa', style: TextStyle(color: Colors.redAccent)),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    final err = await ScheduleApi.deleteSchedule(s.id);
    if (err != null) {
      _snack(err, error: true);
    } else {
      _snack('Đã xóa lịch.');
    }
    _load();
  }

  DeviceType _typeOf(Schedule s) {
    final device = _deviceOf(s);
    return deviceTypeOf('${device?['name'] ?? ''}');
  }

  Future<void> _openForm({Schedule? edit}) async {
    if (_devices.isEmpty) {
      _snack('Chưa tải được danh sách thiết bị.', error: true);
      return;
    }
    final saved = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppColors.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      builder: (_) => _ScheduleForm(devices: _devices, edit: edit),
    );
    if (saved == true) {
      _snack(edit == null ? 'Đã tạo lịch mới.' : 'Đã cập nhật lịch.');
      _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Scaffold(
        backgroundColor: Colors.transparent,
        floatingActionButton: FloatingActionButton(
          onPressed: () => _openForm(),
          backgroundColor: AppColors.primary,
          child: const Icon(Icons.add, color: Colors.white),
        ),
        body: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(24, 16, 24, 8),
              child: Row(
                children: [
                  Icon(Icons.schedule, color: AppColors.primary),
                  SizedBox(width: 8),
                  Text('Hẹn giờ thiết bị',
                      style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: AppColors.textMain)),
                ],
              ),
            ),
            if (_offline)
              Container(
                width: double.infinity,
                color: Colors.redAccent,
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: const Text('Mất kết nối máy chủ. Kéo xuống để thử lại.',
                    textAlign: TextAlign.center, style: TextStyle(color: Colors.white, fontSize: 12)),
              ),
            Expanded(
              child: _loading
                  ? const Center(child: CircularProgressIndicator(color: AppColors.primary))
                  : RefreshIndicator(
                      onRefresh: _load,
                      color: AppColors.primary,
                      backgroundColor: AppColors.surface,
                      child: _schedules.isEmpty
                          ? ListView(
                              physics: const AlwaysScrollableScrollPhysics(),
                              children: const [
                                SizedBox(height: 120),
                                Center(
                                  child: Text('Chưa có lịch nào.\nBấm ＋ để tạo lịch hẹn giờ đầu tiên.',
                                      textAlign: TextAlign.center,
                                      style: TextStyle(color: AppColors.textSub)),
                                ),
                              ],
                            )
                          : ListView.builder(
                              physics: const AlwaysScrollableScrollPhysics(),
                              padding: const EdgeInsets.fromLTRB(24, 8, 24, 100),
                              itemCount: _schedules.length,
                              itemBuilder: (context, index) {
                                final s = _schedules[index];
                                return _buildScheduleCard(s)
                                    .animate()
                                    .fade(duration: 300.ms)
                                    .slideY(begin: 0.1);
                              },
                            ),
                    ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildScheduleCard(Schedule s) {
    final device = _deviceOf(s);
    final deviceName = '${device?['name'] ?? s.deviceId}';
    final type = deviceTypeOf(deviceName);
    final enabled = s.enabled;
    final color = enabled ? AppColors.primary : AppColors.textSub;
    // Khoảng qua đêm (end < start): đánh dấu giờ kết thúc thuộc hôm sau.
    final overnight = s.isRange && s.endTime!.compareTo(s.time) < 0;
    final timeText = s.isRange ? '${s.time} → ${s.endTime}${overnight ? '⁺¹' : ''}' : s.time;

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: enabled ? AppColors.primary.withValues(alpha: 0.35) : Colors.white10),
      ),
      child: InkWell(
        onTap: () => _openForm(edit: s),
        child: Row(
          children: [
            // Giờ lớn bên trái (khoảng dài hơn nên chữ nhỏ lại để không tràn)
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(timeText,
                    style: TextStyle(
                        fontSize: s.isRange ? 18 : 26, fontWeight: FontWeight.bold,
                        color: enabled ? AppColors.textMain : AppColors.textSub)),
                Row(
                  children: [
                    Text(_daysLabel(s.days), style: TextStyle(fontSize: 11, color: color)),
                    if (s.oneShot)
                      Padding(
                        padding: const EdgeInsets.only(left: 6),
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                          decoration: BoxDecoration(
                            color: AppColors.primary.withValues(alpha: 0.15),
                            borderRadius: BorderRadius.circular(6),
                          ),
                          child: Text('1 lần', style: TextStyle(fontSize: 9, color: color)),
                        ),
                      ),
                  ],
                ),
              ],
            ),
            const SizedBox(width: 16),
            // Thông tin hành động + thiết bị
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    s.name.isNotEmpty ? s.name : _actionSummary(s, type),
                    style: const TextStyle(color: AppColors.textMain, fontWeight: FontWeight.w600),
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: 2),
                  Text(
                    '${_actionSummary(s, type)} • $deviceName',
                    style: const TextStyle(color: AppColors.textSub, fontSize: 12),
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
            Switch.adaptive(
              value: enabled,
              activeTrackColor: AppColors.primary,
              onChanged: (v) => _toggleEnabled(s, v),
            ),
            IconButton(
              icon: const Icon(Icons.delete_outline, color: AppColors.textSub, size: 20),
              onPressed: () => _delete(s),
            ),
          ],
        ),
      ),
    );
  }
}

// =========================================================
// FORM THÊM / SỬA LỊCH (bottom sheet)
// =========================================================
class _ScheduleForm extends StatefulWidget {
  final List<Map<String, dynamic>> devices;
  final Schedule? edit; // null = tạo mới

  const _ScheduleForm({required this.devices, this.edit});

  @override
  State<_ScheduleForm> createState() => _ScheduleFormState();
}

class _ScheduleFormState extends State<_ScheduleForm> {
  late String _deviceId;
  late String _actionKey; // key của _ActionOption đang chọn
  late TimeOfDay _time;
  late Set<int> _days; // rỗng = mỗi ngày
  late final TextEditingController _nameCtrl;
  bool _saving = false;
  // ---- Lịch KHOẢNG (bắt đầu -> kết thúc) ----
  bool _isRange = false;
  late TimeOfDay _endTime;
  late String _endActionKey;

  Map<String, dynamic> get _device =>
      widget.devices.firstWhere((d) => '${d['id']}' == _deviceId, orElse: () => widget.devices.first);

  DeviceType get _deviceType => deviceTypeOf('${_device['name'] ?? ''}');
  List<_ActionOption> get _actions => _actionsFor(_deviceType);

  @override
  void initState() {
    super.initState();
    final e = widget.edit;
    _deviceId = e?.deviceId ?? '${widget.devices.first['id']}';
    // Nếu device của lịch cũ đã bị xóa -> quay về thiết bị đầu tiên.
    if (!widget.devices.any((d) => '${d['id']}' == _deviceId)) {
      _deviceId = '${widget.devices.first['id']}';
    }
    _actionKey = e != null ? '${e.actionType}:${e.actionValue ?? ''}' : _actions.first.key;
    if (!_actions.any((a) => a.key == _actionKey)) _actionKey = _actions.first.key;
    final parts = (e?.time ?? '07:00').split(':');
    _time = TimeOfDay(hour: int.tryParse(parts[0]) ?? 7, minute: int.tryParse(parts[1]) ?? 0);
    // Khoảng: nạp giờ/hành động kết thúc từ lịch cũ; mặc định = giờ bắt đầu + 1h.
    _isRange = e?.isRange ?? false;
    final endParts = (e?.endTime ?? '').split(':');
    _endTime = _isRange
        ? TimeOfDay(
            hour: int.tryParse(endParts[0]) ?? ((_time.hour + 1) % 24),
            minute: int.tryParse(endParts.length > 1 ? endParts[1] : '') ?? _time.minute)
        : TimeOfDay(hour: (_time.hour + 1) % 24, minute: _time.minute);
    _endActionKey = _isRange ? '${e!.endActionType}:${e.endActionValue ?? ''}' : _actions.first.key;
    if (!_actions.any((a) => a.key == _endActionKey)) _endActionKey = _actions.first.key;
    _days = (e?.days ?? '')
        .split(',')
        .map((p) => int.tryParse(p.trim()))
        .whereType<int>()
        .where((d) => d >= 0 && d <= 6)
        .toSet();
    _nameCtrl = TextEditingController(text: e?.name ?? '');
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    super.dispose();
  }

  Future<void> _pickTime() async {
    final picked = await showTimePicker(context: context, initialTime: _time);
    if (picked != null) setState(() => _time = picked);
  }

  Future<void> _pickEndTime() async {
    final picked = await showTimePicker(context: context, initialTime: _endTime);
    if (picked != null) setState(() => _endTime = picked);
  }

  String _fmt(TimeOfDay t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  Future<void> _save() async {
    if (_saving) return;
    if (_isRange && _endTime.hour == _time.hour && _endTime.minute == _time.minute) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Giờ kết thúc phải khác giờ bắt đầu.'),
          backgroundColor: Colors.redAccent));
      return;
    }
    setState(() => _saving = true);
    final action = _actions.firstWhere((a) => a.key == _actionKey);
    final endAction = _actions.firstWhere((a) => a.key == _endActionKey);
    final timeStr = _fmt(_time);
    final daysStr = (_days.toList()..sort()).join(',');
    final brand = '${_device['brand']}'.toLowerCase();

    String? err;
    if (widget.edit == null) {
      err = await ScheduleApi.createSchedule(
        name: _nameCtrl.text.trim(),
        brand: brand,
        deviceId: _deviceId,
        actionType: action.actionType,
        actionValue: action.actionValue,
        time: timeStr,
        days: daysStr,
        endTime: _isRange ? _fmt(_endTime) : null,
        endActionType: _isRange ? endAction.actionType : null,
        endActionValue: _isRange ? endAction.actionValue : null,
      );
    } else {
      err = await ScheduleApi.updateSchedule(widget.edit!.id, {
        'name': _nameCtrl.text.trim(),
        'brand': brand,
        'device_id': _deviceId,
        'action_type': action.actionType,
        'action_value': action.actionValue,
        'time': timeStr,
        'days': daysStr,
        // Gửi null tường minh khi chuyển về "Một lần" — backend hiểu là xóa khoảng.
        'end_time': _isRange ? _fmt(_endTime) : null,
        'end_action_type': _isRange ? endAction.actionType : null,
        'end_action_value': _isRange ? endAction.actionValue : null,
      });
    }

    if (!mounted) return;
    if (err != null) {
      setState(() => _saving = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(err), backgroundColor: Colors.redAccent),
      );
    } else {
      Navigator.pop(context, true);
    }
  }

  /// Ô chọn giờ (dùng cho cả giờ bắt đầu lẫn giờ kết thúc).
  Widget _timeTile(String value, VoidCallback onTap) => InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          decoration: BoxDecoration(
            color: AppColors.card,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.white10),
          ),
          child: Row(
            children: [
              const Icon(Icons.access_time, color: AppColors.primary, size: 20),
              const SizedBox(width: 12),
              Text(value,
                  style: const TextStyle(
                      fontSize: 20, fontWeight: FontWeight.bold, color: AppColors.textMain)),
            ],
          ),
        ),
      );

  /// Dàn ChoiceChip chọn hành động (dùng cho hành động bắt đầu & kết thúc).
  Widget _actionChips(String selectedKey, ValueChanged<String> onSelect) => Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          for (final a in _actions)
            ChoiceChip(
              label: Text(a.label,
                  style: TextStyle(
                      fontSize: 12,
                      color: selectedKey == a.key ? Colors.white : AppColors.textMain)),
              selected: selectedKey == a.key,
              selectedColor: AppColors.primary,
              backgroundColor: AppColors.card,
              onSelected: (_) => onSelect(a.key),
            ),
        ],
      );

  @override
  Widget build(BuildContext context) {
    final timeStr = _fmt(_time);
    // end < start = khoảng qua đêm -> giờ kết thúc thuộc ngày hôm sau.
    final endMinutes = _endTime.hour * 60 + _endTime.minute;
    final startMinutes = _time.hour * 60 + _time.minute;
    final overnight = _isRange && endMinutes < startMinutes;

    return Padding(
      // Đẩy form lên trên bàn phím khi nhập tên.
      padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(24, 20, 24, 32),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              widget.edit == null ? 'Tạo lịch hẹn giờ' : 'Sửa lịch hẹn giờ',
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: AppColors.textMain),
            ),
            const SizedBox(height: 20),

            // ---- Thiết bị ----
            const Text('Thiết bị', style: TextStyle(color: AppColors.textSub, fontSize: 12)),
            const SizedBox(height: 6),
            DropdownButtonFormField<String>(
              initialValue: _deviceId,
              dropdownColor: AppColors.card,
              style: const TextStyle(color: AppColors.textMain),
              decoration: _inputDecoration(),
              items: [
                for (final d in widget.devices)
                  DropdownMenuItem(value: '${d['id']}', child: Text('${d['name']}')),
              ],
              onChanged: (v) {
                if (v == null) return;
                setState(() {
                  _deviceId = v;
                  // Loại thiết bị đổi -> danh sách hành động đổi theo (cả 2 mốc).
                  _actionKey = _actions.first.key;
                  _endActionKey = _actions.first.key;
                });
              },
            ),
            const SizedBox(height: 16),

            // ---- Loại lịch: Một lần (1 mốc) / Khoảng (bắt đầu -> kết thúc) ----
            const Text('Loại lịch', style: TextStyle(color: AppColors.textSub, fontSize: 12)),
            const SizedBox(height: 6),
            SizedBox(
              width: double.infinity,
              child: SegmentedButton<bool>(
                segments: const [
                  ButtonSegment(value: false, label: Text('Một mốc', style: TextStyle(fontSize: 12))),
                  ButtonSegment(value: true, label: Text('Khoảng', style: TextStyle(fontSize: 12))),
                ],
                selected: {_isRange},
                onSelectionChanged: (v) => setState(() => _isRange = v.first),
                style: SegmentedButton.styleFrom(
                  backgroundColor: AppColors.card,
                  foregroundColor: AppColors.textMain,
                  selectedBackgroundColor: AppColors.primary,
                  selectedForegroundColor: Colors.white,
                  side: const BorderSide(color: Colors.white10),
                ),
                showSelectedIcon: false,
              ),
            ),
            const SizedBox(height: 16),

            // ---- Hành động (bắt đầu) ----
            Text(_isRange ? 'Hành động bắt đầu' : 'Hành động',
                style: const TextStyle(color: AppColors.textSub, fontSize: 12)),
            const SizedBox(height: 6),
            _actionChips(_actionKey, (k) => setState(() => _actionKey = k)),
            const SizedBox(height: 16),

            // ---- Giờ (bắt đầu) ----
            Text(_isRange ? 'Giờ bắt đầu' : 'Giờ kích hoạt',
                style: const TextStyle(color: AppColors.textSub, fontSize: 12)),
            const SizedBox(height: 6),
            _timeTile(timeStr, _pickTime),
            const SizedBox(height: 16),

            // ---- Kết thúc (chỉ với lịch khoảng) ----
            if (_isRange) ...[
              const Text('Giờ kết thúc', style: TextStyle(color: AppColors.textSub, fontSize: 12)),
              const SizedBox(height: 6),
              _timeTile(_fmt(_endTime), _pickEndTime),
              if (overnight)
                const Padding(
                  padding: EdgeInsets.only(top: 6),
                  child: Text('Kết thúc vào ngày hôm sau (lịch qua đêm).',
                      style: TextStyle(color: AppColors.primary, fontSize: 11)),
                ),
              const SizedBox(height: 16),
              const Text('Hành động kết thúc', style: TextStyle(color: AppColors.textSub, fontSize: 12)),
              const SizedBox(height: 6),
              _actionChips(_endActionKey, (k) => setState(() => _endActionKey = k)),
              const SizedBox(height: 16),
            ],

            // ---- Ngày lặp ----
            const Text('Lặp lại (bỏ trống = mỗi ngày)',
                style: TextStyle(color: AppColors.textSub, fontSize: 12)),
            const SizedBox(height: 6),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (var d = 0; d < 7; d++)
                  FilterChip(
                    label: Text(_dayLabels[d],
                        style: TextStyle(
                            fontSize: 12,
                            color: _days.contains(d) ? Colors.white : AppColors.textMain)),
                    selected: _days.contains(d),
                    selectedColor: AppColors.primary,
                    backgroundColor: AppColors.card,
                    showCheckmark: false,
                    onSelected: (v) =>
                        setState(() => v ? _days.add(d) : _days.remove(d)),
                  ),
              ],
            ),
            const SizedBox(height: 16),

            // ---- Tên (tùy chọn) ----
            const Text('Tên lịch (tùy chọn)', style: TextStyle(color: AppColors.textSub, fontSize: 12)),
            const SizedBox(height: 6),
            TextField(
              controller: _nameCtrl,
              style: const TextStyle(color: AppColors.textMain),
              decoration: _inputDecoration(hint: 'VD: Bật lọc mạnh buổi sáng'),
            ),
            const SizedBox(height: 24),

            // ---- Nút lưu ----
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: _saving ? null : _save,
                style: FilledButton.styleFrom(
                  backgroundColor: AppColors.primary,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                ),
                child: _saving
                    ? const SizedBox(
                        width: 20, height: 20,
                        child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
                    : Text(widget.edit == null ? 'Tạo lịch' : 'Lưu thay đổi',
                        style: const TextStyle(fontSize: 15, fontWeight: FontWeight.bold)),
              ),
            ),
          ],
        ),
      ),
    );
  }

  InputDecoration _inputDecoration({String? hint}) => InputDecoration(
        hintText: hint,
        hintStyle: const TextStyle(color: AppColors.textSub, fontSize: 13),
        filled: true,
        fillColor: AppColors.card,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide.none,
        ),
      );
}
