import 'package:flutter/material.dart';

import '../core/device_type.dart';
import '../core/scene_api.dart';
import '../theme/app_colors.dart';

/// Icon chọn được cho kịch bản (tên lưu ở backend -> IconData ở app).
const Map<String, IconData> sceneIcons = {
  'home': Icons.home_rounded,
  'logout': Icons.logout_rounded,
  'bedtime': Icons.bedtime_rounded,
  'wb_sunny': Icons.wb_sunny_rounded,
  'water_drop': Icons.water_drop_rounded,
  'pets': Icons.pets_rounded,
  'movie': Icons.movie_rounded,
  'shield': Icons.shield_rounded,
};

IconData sceneIconOf(Scene s) => sceneIcons[s.icon] ?? Icons.auto_awesome_rounded;

DeviceType _typeOf(Map device) =>
    deviceTypeOf('${device['name'] ?? ''}', category: device['category'] as String?);

/// Kịch bản có hành động MỞ CỬA không — chạy kịch bản kiểu này cần xác nhận.
bool sceneOpensDoor(Scene s, List<dynamic> devices) => s.actions.any((a) {
      final d = devices.cast<Map>().where((d) => '${d['id']}' == a.deviceId).firstOrNull;
      return d != null && _typeOf(d) == DeviceType.curtain && a.actionValue == 'open';
    });

/// Tối đa điều kiện / kịch bản — khớp MAX_CONDITIONS của backend.
const int maxSceneConditions = 10;

String _hhmm(TimeOfDay t) => '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

TimeOfDay? _parseHhmm(String? s) {
  final parts = (s ?? '').split(':');
  if (parts.length != 2) return null;
  final h = int.tryParse(parts[0]), m = int.tryParse(parts[1]);
  return (h == null || m == null) ? null : TimeOfDay(hour: h, minute: m);
}

/// Mô tả 1 điều kiện bằng tiếng Việt, vd "Từ 22:00 đến 06:00 (qua đêm)", "Máy bơm đang tắt".
String describeSceneCondition(SceneCondition c, List<dynamic> devices) {
  if (c.type == SceneCondition.timeRange) {
    return 'Từ ${c.start} đến ${c.end}${c.isOvernight ? ' (qua đêm)' : ''}';
  }
  if (c.type == SceneCondition.deviceState) {
    final d = devices.cast<Map>().where((d) => '${d['id']}' == c.deviceId).firstOrNull;
    if (d == null) return 'Thiết bị đã xóa hoặc ngoài quyền — sẽ không đạt';
    final label = conditionStateOptions(_typeOf(d)).where((o) => o.$1 == c.expectedState).firstOrNull?.$2;
    return '${d['name']} ${(label ?? c.expectedState ?? '?').toLowerCase()}';
  }
  return 'Điều kiện chưa hỗ trợ trên bản app này';
}

/// Tạo / sửa kịch bản. Trả `true` qua Navigator.pop khi có thay đổi (lưu/xóa).
class SceneEditorScreen extends StatefulWidget {
  final Scene? scene;          // null = tạo mới
  final List<dynamic> devices; // thiết bị người dùng thấy được (từ dashboard)

  const SceneEditorScreen({super.key, this.scene, required this.devices});

  @override
  State<SceneEditorScreen> createState() => _SceneEditorScreenState();
}

class _SceneEditorScreenState extends State<SceneEditorScreen> {
  late final TextEditingController _name = TextEditingController(text: widget.scene?.name ?? '');
  late String _icon = widget.scene?.icon ?? 'home';
  late final List<SceneAction> _actions = [...?widget.scene?.actions];
  late String _operator = widget.scene?.conditions.operator ?? 'AND';
  late final List<SceneCondition> _conditions = [...?widget.scene?.conditions.items];
  bool _saving = false;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  Map? _device(String id) => widget.devices.cast<Map>().where((d) => '${d['id']}' == id).firstOrNull;

  void _snack(String msg, {bool error = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(msg),
      backgroundColor: error ? Colors.redAccent : context.palette.primary,
    ));
  }

  Future<void> _addAction() async {
    final p = context.palette;
    // Bước 1: chọn thiết bị.
    final device = await showModalBottomSheet<Map>(
      context: context,
      backgroundColor: p.surface,
      builder: (ctx) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            const ListTile(title: Text('Chọn thiết bị', style: TextStyle(fontWeight: FontWeight.bold))),
            for (final d in widget.devices.cast<Map>())
              ListTile(
                leading: const Icon(Icons.devices_other),
                title: Text('${d['name']}'),
                subtitle: d['zone_name'] != null ? Text('${d['zone_name']}') : null,
                onTap: () => Navigator.pop(ctx, d),
              ),
          ],
        ),
      ),
    );
    if (device == null || !mounted) return;

    // Bước 2: chọn hành động hợp lệ với loại thiết bị.
    final options = deviceActionOptions(_typeOf(device));
    final opt = await showModalBottomSheet<DeviceActionOption>(
      context: context,
      backgroundColor: p.surface,
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('${device['name']}', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final o in options) ActionChip(label: Text(o.label), onPressed: () => Navigator.pop(ctx, o)),
                ],
              ),
            ],
          ),
        ),
      ),
    );
    if (opt == null) return;
    setState(() => _actions.add(SceneAction('${device['id']}', opt.actionType, opt.actionValue)));
  }

  // ---------------- Điều kiện ----------------
  Future<void> _addCondition() async {
    final p = context.palette;
    final type = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: p.surface,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const ListTile(title: Text('Loại điều kiện', style: TextStyle(fontWeight: FontWeight.bold))),
            ListTile(
              leading: const Icon(Icons.schedule),
              title: const Text('Khoảng thời gian'),
              subtitle: const Text('Chỉ chạy trong khung giờ, vd 22:00 → 06:00'),
              onTap: () => Navigator.pop(ctx, SceneCondition.timeRange),
            ),
            ListTile(
              leading: const Icon(Icons.sensors),
              title: const Text('Trạng thái thiết bị'),
              subtitle: const Text('Vd máy bơm đang tắt, cửa cuốn đang đóng'),
              onTap: () => Navigator.pop(ctx, SceneCondition.deviceState),
            ),
          ],
        ),
      ),
    );
    if (type == null || !mounted) return;
    final c = type == SceneCondition.timeRange ? await _pickTimeRange() : await _pickDeviceState();
    if (c != null && mounted) setState(() => _conditions.add(c));
  }

  Future<void> _editCondition(int i) async {
    final old = _conditions[i];
    SceneCondition? c;
    if (old.type == SceneCondition.timeRange) {
      c = await _pickTimeRange(old);
    } else if (old.type == SceneCondition.deviceState) {
      c = await _pickDeviceState(old);
    }
    if (c != null && mounted) setState(() => _conditions[i] = c!);
  }

  Future<SceneCondition?> _pickTimeRange([SceneCondition? old]) async {
    final start = await showTimePicker(
      context: context,
      helpText: 'CHẠY TỪ GIỜ',
      initialTime: _parseHhmm(old?.start) ?? const TimeOfDay(hour: 22, minute: 0),
    );
    if (start == null || !mounted) return null;
    final end = await showTimePicker(
      context: context,
      helpText: 'ĐẾN GIỜ (qua nửa đêm được)',
      initialTime: _parseHhmm(old?.end) ?? const TimeOfDay(hour: 6, minute: 0),
    );
    if (end == null) return null;
    // Trùng giờ là mơ hồ (0 phút hay cả ngày?) — backend cũng từ chối.
    if (start == end) {
      _snack('Giờ bắt đầu và giờ kết thúc phải khác nhau.', error: true);
      return null;
    }
    return SceneCondition.time(_hhmm(start), _hhmm(end));
  }

  Future<SceneCondition?> _pickDeviceState([SceneCondition? old]) async {
    final p = context.palette;
    // Sửa điều kiện có sẵn: giữ thiết bị, chỉ chọn lại trạng thái.
    Map? device = old?.deviceId == null ? null : _device(old!.deviceId!);
    if (device == null) {
      final candidates =
          widget.devices.cast<Map>().where((d) => conditionStateOptions(_typeOf(d)).isNotEmpty).toList();
      if (candidates.isEmpty) {
        _snack('Không có thiết bị nào dùng làm điều kiện được.', error: true);
        return null;
      }
      device = await showModalBottomSheet<Map>(
        context: context,
        backgroundColor: p.surface,
        builder: (ctx) => SafeArea(
          child: ListView(
            shrinkWrap: true,
            children: [
              const ListTile(title: Text('Kiểm tra thiết bị nào?', style: TextStyle(fontWeight: FontWeight.bold))),
              for (final d in candidates)
                ListTile(
                  leading: const Icon(Icons.devices_other),
                  title: Text('${d['name']}'),
                  subtitle: d['zone_name'] != null ? Text('${d['zone_name']}') : null,
                  onTap: () => Navigator.pop(ctx, d),
                ),
            ],
          ),
        ),
      );
    }
    if (device == null || !mounted) return null;
    final type = _typeOf(device);
    final picked = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: p.surface,
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('${device!['name']} phải...', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final (value, label) in conditionStateOptions(type))
                    ChoiceChip(
                      label: Text(label),
                      selected: old?.expectedState == value,
                      onSelected: (_) => Navigator.pop(ctx, value),
                    ),
                ],
              ),
              const SizedBox(height: 12),
              Text(
                type == DeviceType.curtain
                    ? 'Trạng thái cửa suy từ lệnh cuối lên cloud — bấm remote RF thì hệ thống không biết. '
                        'Cửa đang chạy hoặc offline = không đạt.'
                    : 'Thiết bị offline hoặc không đọc được trạng thái = không đạt.',
                style: TextStyle(color: p.textSub, fontSize: 12),
              ),
            ],
          ),
        ),
      ),
    );
    if (picked == null) return null;
    return SceneCondition.device('${device['id']}', picked);
  }

  Future<void> _save() async {
    final name = _name.text.trim();
    if (name.isEmpty) return _snack('Đặt tên cho kịch bản.', error: true);
    if (_actions.isEmpty) return _snack('Thêm ít nhất 1 hành động.', error: true);
    setState(() => _saving = true);
    final err = await SceneApi.save(
      id: widget.scene?.id,
      name: name,
      icon: _icon,
      actions: _actions,
      conditions: SceneConditions(operator: _operator, items: _conditions),
    );
    if (!mounted) return;
    setState(() => _saving = false);
    if (err != null) return _snack(err, error: true);
    Navigator.pop(context, true);
  }

  Future<void> _delete() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Xóa kịch bản "${widget.scene!.name}"?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Hủy')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Xóa', style: TextStyle(color: Colors.redAccent)),
          ),
        ],
      ),
    );
    if (ok != true) return;
    final err = await SceneApi.delete(widget.scene!.id);
    if (!mounted) return;
    if (err != null) return _snack(err, error: true);
    Navigator.pop(context, true);
  }

  List<Widget> _conditionsSection(AppPalette p) => [
        Text('ĐIỀU KIỆN (tùy chọn)', style: TextStyle(color: p.textSub, fontSize: 12, fontWeight: FontWeight.w600)),
        const SizedBox(height: 4),
        Text(
          _conditions.isEmpty
              ? 'Không có điều kiện — bấm là chạy.'
              : 'Không đạt (hoặc thiết bị offline) thì kịch bản bỏ qua, không gửi lệnh nào.',
          style: TextStyle(color: p.textSub, fontSize: 12),
        ),
        if (_conditions.length >= 2) ...[
          const SizedBox(height: 8),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'AND', label: Text('Tất cả đều đúng', style: TextStyle(fontSize: 12))),
              ButtonSegment(value: 'OR', label: Text('Chỉ cần 1 đúng', style: TextStyle(fontSize: 12))),
            ],
            selected: {_operator},
            showSelectedIcon: false,
            onSelectionChanged: (v) => setState(() => _operator = v.first),
            style: SegmentedButton.styleFrom(
              backgroundColor: p.card,
              foregroundColor: p.textMain,
              selectedBackgroundColor: p.primary,
              selectedForegroundColor: Colors.white,
              side: BorderSide(color: p.outline),
            ),
          ),
        ],
        const SizedBox(height: 8),
        for (var i = 0; i < _conditions.length; i++) ...[
          if (i > 0)
            Center(
              child: Text(_operator == 'OR' ? 'HOẶC' : 'VÀ',
                  style: TextStyle(color: p.textSub, fontSize: 11, fontWeight: FontWeight.w700)),
            ),
          Card(
            color: p.card,
            child: ListTile(
              leading: Icon(_conditions[i].type == SceneCondition.timeRange ? Icons.schedule : Icons.sensors),
              title: Text(describeSceneCondition(_conditions[i], widget.devices)),
              onTap: () => _editCondition(i),
              trailing: IconButton(
                tooltip: 'Xóa điều kiện',
                icon: const Icon(Icons.close),
                onPressed: () => setState(() => _conditions.removeAt(i)),
              ),
            ),
          ),
        ],
        const SizedBox(height: 8),
        OutlinedButton.icon(
          onPressed: _conditions.length >= maxSceneConditions ? null : _addCondition,
          icon: const Icon(Icons.rule),
          label: const Text('Thêm điều kiện'),
        ),
      ];

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.scene == null ? 'Kịch bản mới' : 'Sửa kịch bản'),
        actions: [
          if (widget.scene != null)
            IconButton(tooltip: 'Xóa', icon: const Icon(Icons.delete_outline, color: Colors.redAccent), onPressed: _delete),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _saving ? null : _save,
        backgroundColor: p.primary,
        foregroundColor: Colors.white,
        icon: _saving
            ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2))
            : const Icon(Icons.check),
        label: const Text('Lưu'),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 100),
        children: [
          TextField(
            controller: _name,
            maxLength: 40,
            style: TextStyle(color: p.textMain),
            decoration: const InputDecoration(labelText: 'Tên kịch bản', hintText: 'Ra khỏi nhà, Đi ngủ...'),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              for (final e in sceneIcons.entries)
                ChoiceChip(
                  label: Icon(e.value, size: 20, color: _icon == e.key ? Colors.white : p.textMain),
                  selected: _icon == e.key,
                  selectedColor: p.primary,
                  showCheckmark: false,
                  onSelected: (_) => setState(() => _icon = e.key),
                ),
            ],
          ),
          const SizedBox(height: 24),
          ..._conditionsSection(p),
          const SizedBox(height: 24),
          Text('HÀNH ĐỘNG (chạy lần lượt từ trên xuống)',
              style: TextStyle(color: p.textSub, fontSize: 12, fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          ReorderableListView(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            buildDefaultDragHandles: false,
            // onReorderItem: newIndex ĐÃ được điều chỉnh cho phần tử bị gỡ ở oldIndex.
            onReorderItem: (oldIndex, newIndex) => setState(() {
              _actions.insert(newIndex, _actions.removeAt(oldIndex));
            }),
            children: [
              for (var i = 0; i < _actions.length; i++)
                Card(
                  key: ValueKey('a$i-${_actions[i].deviceId}-${_actions[i].actionType}-${_actions[i].actionValue}'),
                  color: p.card,
                  child: ListTile(
                    leading: ReorderableDragStartListener(index: i, child: const Icon(Icons.drag_indicator)),
                    title: Text('${_device(_actions[i].deviceId)?['name'] ?? 'Thiết bị đã xóa'}'),
                    subtitle: Text(_device(_actions[i].deviceId) == null
                        ? 'Sẽ được bỏ qua khi chạy'
                        : deviceActionLabel(_actions[i].actionType, _actions[i].actionValue,
                            _typeOf(_device(_actions[i].deviceId)!))),
                    trailing: IconButton(
                      icon: const Icon(Icons.close),
                      onPressed: () => setState(() => _actions.removeAt(i)),
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: widget.devices.isEmpty ? null : _addAction,
            icon: const Icon(Icons.add),
            label: const Text('Thêm hành động'),
          ),
        ],
      ),
    );
  }
}
