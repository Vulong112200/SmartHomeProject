import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../core/floor_plan.dart';
import '../../theme/app_colors.dart';
import 'floor_plan_painter.dart' show formatMeters;

/// Các bảng nhỏ của chế độ "Sửa sơ đồ" (chỉ chủ nhà). Chỉ TRẢ VỀ ý định của
/// người dùng — màn Sơ đồ tự áp vào bản nháp, chưa lưu gì lên máy chủ.

Future<T?> _sheet<T>(BuildContext context, Widget Function(BuildContext) builder) => showModalBottomSheet<T>(
      context: context,
      backgroundColor: context.palette.surface,
      showDragHandle: true,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: EdgeInsets.fromLTRB(20, 0, 20, 20 + MediaQuery.of(ctx).viewInsets.bottom),
          child: builder(ctx),
        ),
      ),
    );

Widget _title(BuildContext context, String text, [String? sub]) => Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(text, style: TextStyle(color: context.palette.textMain, fontSize: 17, fontWeight: FontWeight.bold)),
          if (sub != null) Text(sub, style: TextStyle(color: context.palette.textSub, fontSize: 13)),
        ],
      ),
    );

/// Ý định sửa phòng.
sealed class RoomEdit {}

class AddDoorEdit extends RoomEdit {
  final Wall wall;
  AddDoorEdit(this.wall);
}

class ResizeRoomEdit extends RoomEdit {
  final double width;
  final double depth;
  ResizeRoomEdit(this.width, this.depth);
}

Future<RoomEdit?> showRoomEditSheet(BuildContext context, PlanRoom room) =>
    _sheet<RoomEdit>(context, (ctx) => _RoomEditBody(room: room));

class _RoomEditBody extends StatefulWidget {
  final PlanRoom room;
  const _RoomEditBody({required this.room});

  @override
  State<_RoomEditBody> createState() => _RoomEditBodyState();
}

class _RoomEditBodyState extends State<_RoomEditBody> {
  late final _w = TextEditingController(text: formatMeters(widget.room.width));
  late final _d = TextEditingController(text: formatMeters(widget.room.depth));
  String? _error;

  @override
  void dispose() {
    _w.dispose();
    _d.dispose();
    super.dispose();
  }

  double? _parse(String s) => double.tryParse(s.trim().replaceAll(',', '.'));

  void _applySize() {
    final w = _parse(_w.text);
    final d = _parse(_d.text);
    if (w == null || d == null || w < 0.5 || d < 0.5 || w > 50 || d > 50) {
      setState(() => _error = 'Kích thước phải từ 0,5 đến 50 m.');
      return;
    }
    Navigator.pop(context, ResizeRoomEdit(w, d));
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = widget.room;
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _title(context, r.name, 'Kéo phòng trên sơ đồ để đổi vị trí so với phòng khác.'),
        Text('Thêm cửa ra vào', style: TextStyle(color: p.textMain, fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final w in Wall.values)
              ActionChip(
                key: ValueKey('add-door-${w.name}'),
                avatar: Icon(Icons.door_front_door_outlined, size: 16, color: p.primary),
                label: Text(wallLabels[w]!),
                onPressed: () => Navigator.pop(context, AddDoorEdit(w)),
              ),
          ],
        ),
        const SizedBox(height: 4),
        Text('Cửa được đặt giữa tường, rộng 0,8 m — kéo dọc tường để chỉnh.',
            style: TextStyle(color: p.textSub, fontSize: 12)),
        const SizedBox(height: 18),
        Text('Kích thước thật (m)', style: TextStyle(color: p.textMain, fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: _w,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(labelText: 'Rộng (ngang)', suffixText: 'm'),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: TextField(
                controller: _d,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(labelText: 'Dài (dọc)', suffixText: 'm'),
              ),
            ),
          ],
        ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(_error!, style: const TextStyle(color: Colors.redAccent, fontSize: 12)),
          ),
        const SizedBox(height: 12),
        Align(
          alignment: Alignment.centerRight,
          child: FilledButton(onPressed: _applySize, child: const Text('Áp dụng kích thước')),
        ),
      ],
    );
  }
}

/// Ý định sửa cửa: null = đóng bảng không đổi; `width` mới; hoặc xóa.
class DoorEdit {
  final bool delete;
  final double? width;
  const DoorEdit.delete()
      : delete = true,
        width = null;
  const DoorEdit.width(this.width) : delete = false;
}

Future<DoorEdit?> showDoorEditSheet(BuildContext context, PlanDoor door, PlanRoom room) =>
    _sheet<DoorEdit>(context, (ctx) => _DoorEditBody(door: door, room: room));

class _DoorEditBody extends StatefulWidget {
  final PlanDoor door;
  final PlanRoom room;
  const _DoorEditBody({required this.door, required this.room});

  @override
  State<_DoorEditBody> createState() => _DoorEditBodyState();
}

class _DoorEditBodyState extends State<_DoorEditBody> {
  late double _width = widget.door.width;

  double get _max => math.max(0.3, math.min(3.0, widget.room.wallLength(widget.door.wall)));

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _title(context, 'Cửa ra vào', '${widget.room.name} • ${wallLabels[widget.door.wall]}'),
        Text('Bề rộng: ${formatMeters(_width)} m', style: TextStyle(color: p.textMain)),
        Slider(
          value: _width.clamp(0.3, _max),
          min: 0.3,
          max: _max,
          divisions: math.max(1, ((_max - 0.3) / 0.05).round()),
          onChanged: (v) => setState(() => _width = (v * 20).roundToDouble() / 20),
        ),
        Row(
          children: [
            TextButton.icon(
              key: const ValueKey('delete-door'),
              onPressed: () => Navigator.pop(context, const DoorEdit.delete()),
              icon: const Icon(Icons.delete_outline, color: Colors.redAccent),
              label: const Text('Xóa cửa', style: TextStyle(color: Colors.redAccent)),
            ),
            const Spacer(),
            FilledButton(onPressed: () => Navigator.pop(context, DoorEdit.width(_width)), child: const Text('Xong')),
          ],
        ),
      ],
    );
  }
}

/// Thiết bị đã đặt: hỏi có bỏ khỏi sơ đồ không. true = bỏ.
Future<bool?> showPlacedDeviceSheet(BuildContext context, String deviceName) => _sheet<bool>(
      context,
      (ctx) => Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _title(ctx, deviceName, 'Kéo icon để đổi vị trí; thả sang phòng khác để chuyển phòng.'),
          TextButton.icon(
            key: const ValueKey('unplace-device'),
            onPressed: () => Navigator.pop(ctx, true),
            icon: const Icon(Icons.remove_circle_outline, color: Colors.redAccent),
            label: const Text('Bỏ khỏi sơ đồ', style: TextStyle(color: Colors.redAccent)),
          ),
        ],
      ),
    );

/// Chọn phòng để đặt thiết bị chưa có vị trí. 1 phòng thì khỏi hỏi.
Future<String?> pickRoom(BuildContext context, List<PlanRoom> rooms, String deviceName) async {
  if (rooms.length == 1) return rooms.first.id;
  return _sheet<String>(
    context,
    (ctx) => Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _title(ctx, 'Đặt "$deviceName" vào phòng nào?'),
        for (final r in rooms)
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: Icon(Icons.meeting_room_outlined, color: ctx.palette.primary),
            title: Text(r.name, style: TextStyle(color: ctx.palette.textMain)),
            subtitle: Text('${formatMeters(r.width)} × ${formatMeters(r.depth)} m',
                style: TextStyle(color: ctx.palette.textSub)),
            onTap: () => Navigator.pop(ctx, r.id),
          ),
      ],
    ),
  );
}
