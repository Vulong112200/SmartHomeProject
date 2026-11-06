import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/gestures.dart' show DragStartBehavior;
import 'package:flutter/material.dart';

import '../../core/auth_service.dart';
import '../../core/device_api.dart';
import '../../core/device_status.dart';
import '../../core/device_type.dart';
import '../../core/floor_plan.dart';
import '../../core/realtime_service.dart';
import '../../theme/app_colors.dart';
import 'device_control_sheet.dart';
import 'floor_plan_painter.dart';
import 'plan_device.dart';
import 'plan_edit_sheets.dart';

/// Nguồn dữ liệu của màn Sơ đồ. Bản thật đi qua ĐÚNG các API đang có
/// (DeviceApi — cùng đường Dashboard dùng, có kiểm quyền + ghi Lịch sử ở
/// backend); test thay bằng bản giả để không bao giờ gửi lệnh thật.
class FloorPlanDataSource {
  final Future<List<Map<String, dynamic>>?> Function() fetchDevices;
  final Future<(FloorPlan?, String?)> Function() fetchPlan;
  final Future<(FloorPlan?, String?)> Function(FloorPlan plan) savePlan;
  final Future<Map<String, dynamic>?> Function(String brand, String deviceId, bool fresh) fetchStatus;
  final Future<bool> Function(String brand, String deviceId, DeviceActionOption option) send;

  /// Các nhịp đọc lại trạng thái (bỏ cache) sau lệnh, tới khi thiết bị xác nhận.
  final List<Duration> confirmDelays;

  const FloorPlanDataSource({
    required this.fetchDevices,
    required this.fetchPlan,
    required this.savePlan,
    required this.fetchStatus,
    required this.send,
    this.confirmDelays = const [
      Duration(milliseconds: 700),
      Duration(milliseconds: 1300),
      Duration(seconds: 2),
      Duration(seconds: 3),
      Duration(seconds: 3),
    ],
  });
}

Future<bool> _sendLive(String brand, String id, DeviceActionOption o) => o.actionType == 'mode'
    ? DeviceApi.sendMode(brand, id, o.actionValue ?? '')
    : DeviceApi.sendAction(brand, id, o.actionType);

Future<Map<String, dynamic>?> _statusLive(String brand, String id, bool fresh) =>
    DeviceApi.fetchStatus(brand, id, fresh: fresh);

const FloorPlanDataSource liveFloorPlanSource = FloorPlanDataSource(
  fetchDevices: DeviceApi.fetchDevices,
  fetchPlan: FloorPlanApi.fetch,
  savePlan: FloorPlanApi.save,
  fetchStatus: _statusLive,
  send: _sendLive,
);

/// Tab "Sơ đồ": mặt bằng 2D, chạm icon để điều khiển; chủ nhà sửa bố cục.
///
/// Tách hẳn khỏi Dashboard (không dùng chung state). Không đụng Home Widget /
/// shortcut: chỉ đọc trạng thái và gửi lệnh qua DeviceApi.
class FloorPlanTab extends StatefulWidget {
  /// Tab có đang hiển thị không (IndexedStack giữ tab sống kể cả khi ẩn) —
  /// chỉ tải lần đầu khi được mở, và chỉ poll khi đang hiển thị.
  final bool isVisible;
  final HouseholdProfile profile;
  final FloorPlanDataSource source;

  /// Cho test điều khiển zoom/pan.
  final TransformationController? transformationController;

  const FloorPlanTab({
    super.key,
    this.isVisible = true,
    this.profile = HouseholdProfile.openHouse,
    this.source = liveFloorPlanSource,
    this.transformationController,
  });

  @override
  State<FloorPlanTab> createState() => _FloorPlanTabState();
}

enum _TargetKind { device, door, room }

class _Target {
  final _TargetKind kind;
  final String id;
  final Offset grab; // (vị trí vật - vị trí ngón tay) theo mét, giữ khi kéo
  const _Target(this.kind, this.id, [this.grab = Offset.zero]);
}

class _FloorPlanTabState extends State<FloorPlanTab> with WidgetsBindingObserver {
  FloorPlanDataSource get _src => widget.source;
  late final TransformationController _transform = widget.transformationController ?? TransformationController();

  bool _loaded = false;
  bool _loading = false;
  String? _planError;
  final ValueNotifier<bool> _serverOffline = ValueNotifier(false);
  Timer? _retryTimer;
  Timer? _pollTimer;
  bool _appActive = true;

  // Thời gian thực (/ws): live ⇒ thôi poll 6s, áp sự kiện vào đúng thiết bị.
  final RealtimeService _rt = RealtimeService.instance;
  StreamSubscription<DeviceEvent>? _rtSub;
  bool _rtLive = false;

  List<PlanDevice> _devices = [];
  final Map<String, ValueNotifier<DeviceLive>> _live = {};
  final Set<String> _reading = {};

  FloorPlan? _plan;

  /// Bản nháp khi đang sửa (null = đang xem).
  FloorPlan? _draft;

  /// Sơ đồ dùng để TÍNH TỶ LỆ. Đứng yên trong lúc kéo (nếu không, kéo phòng ra
  /// xa làm khung bao đổi ⇒ cả sơ đồ co giãn ngay dưới ngón tay); cập nhật khi thả.
  FloorPlan? _fitPlan;
  PlanGeometry? _geometry;
  _Target? _drag;
  bool _saving = false;

  bool get _editing => _draft != null;
  FloorPlan? get _shown => _draft ?? _plan;
  bool get _canEdit => widget.profile.canAdmin;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _rtLive = _rt.isLive;
    _rtSub = _rt.events.listen(_onRealtimeEvent);
    _rt.status.addListener(_onRealtimeStatus);
    if (widget.isVisible) _load();
  }

  void _onRealtimeStatus() {
    final live = _rt.isLive;
    if (!mounted || live == _rtLive) return;
    _rtLive = live;
    // Vừa nối (lại) khi đang xem: đồng bộ 1 lần (sự kiện lúc mất kết nối đã lỡ).
    if (live && _loaded && widget.isVisible && _appActive) _refreshAll();
    _syncPolling();
  }

  void _onRealtimeEvent(DeviceEvent e) {
    final s = e.state;
    final n = _live[e.deviceId];
    // Đang gửi lệnh: vòng xác nhận tự cập nhật (giống poll — không ghi đè).
    if (s == null || n == null || n.value.sending || !mounted) return;
    n.value = n.value.copyWith(status: s, readFailures: 0);
  }

  @override
  void didUpdateWidget(covariant FloorPlanTab old) {
    super.didUpdateWidget(old);
    if (widget.isVisible && !old.isVisible) {
      _loaded ? _refreshAll() : _load();
    }
    _syncPolling();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final active = state == AppLifecycleState.resumed;
    if (active == _appActive) return;
    _appActive = active;
    if (active && widget.isVisible && _loaded) _refreshAll();
    _syncPolling();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _rtSub?.cancel();
    _rt.status.removeListener(_onRealtimeStatus);
    _retryTimer?.cancel();
    _pollTimer?.cancel();
    if (widget.transformationController == null) _transform.dispose();
    for (final n in _live.values) {
      n.dispose();
    }
    _serverOffline.dispose();
    super.dispose();
  }

  // ------------------------------------------------------------ tải dữ liệu
  Future<void> _load() async {
    if (_loading) return;
    _loading = true;
    final results = await Future.wait<Object?>([_src.fetchDevices(), _src.fetchPlan()]);
    _loading = false;
    if (!mounted) return;
    final devices = results[0] as List<Map<String, dynamic>>?;
    final (plan, planErr) = results[1] as (FloorPlan?, String?);

    if (devices == null) {
      _goOffline();
      return;
    }
    _retryTimer?.cancel();
    _serverOffline.value = false;
    final list = devices.map(PlanDevice.fromApi).toList();
    final ids = {for (final d in list) d.id};
    setState(() {
      _devices = list;
      for (final id in ids) {
        _live.putIfAbsent(id, () => ValueNotifier(const DeviceLive()));
      }
      for (final gone in _live.keys.where((k) => !ids.contains(k)).toList()) {
        _live.remove(gone)?.dispose();
      }
      if (plan != null) {
        _planError = null;
        if (!_editing) {
          _plan = plan;
          _fitPlan = plan;
        }
      } else if (_plan == null) {
        _planError = planErr ?? 'Không tải được sơ đồ.';
      }
      _loaded = true;
    });
    _refreshAll();
    _syncPolling();
  }

  void _goOffline() {
    _serverOffline.value = true;
    setState(() => _loaded = _loaded || _plan != null);
    _retryTimer?.cancel();
    _retryTimer = Timer(const Duration(seconds: 5), () {
      if (mounted && widget.isVisible) _load();
    });
  }

  /// Poll 6s CHỈ khi tab hiển thị + app ở foreground (giống Dashboard: 2 tab
  /// không bao giờ cùng poll vì chỉ 1 tab hiển thị một lúc) VÀ /ws không live
  /// (dự phòng — /ws live thì máy chủ đẩy thay đổi về).
  void _syncPolling() {
    final active = widget.isVisible && _appActive && _loaded && !_rtLive;
    if (!active) {
      _pollTimer?.cancel();
      _pollTimer = null;
    } else {
      _pollTimer ??= Timer.periodic(const Duration(seconds: 6), (_) => _poll());
    }
  }

  void _poll() {
    for (final d in _devices) {
      if (needsPolling(d.type)) _readStatus(d);
    }
  }

  /// Đọc trạng thái mọi thiết bị (máy cho ăn chỉ đọc ở đây + sau lệnh).
  void _refreshAll() {
    for (final d in _devices) {
      _readStatus(d);
    }
  }

  Future<void> _readStatus(PlanDevice d, {bool fresh = false}) async {
    final n = _live[d.id];
    if (n == null || n.value.sending || _reading.contains(d.id)) return;
    _reading.add(d.id);
    final s = await _src.fetchStatus(d.brand, d.id, fresh);
    _reading.remove(d.id);
    if (!mounted) return;
    final cur = _live[d.id];
    // Đang gửi lệnh: vòng xác nhận tự cập nhật, poll không được ghi đè.
    if (cur == null || cur.value.sending) return;
    cur.value = s != null
        ? cur.value.copyWith(status: s, readFailures: 0)
        : cur.value.copyWith(readFailures: cur.value.readFailures + 1);
  }

  // ------------------------------------------------------------ điều khiển
  /// Gửi lệnh qua API có sẵn, rồi đọc lại trạng thái THẬT (bỏ cache) tới khi
  /// thiết bị xác nhận. Không bao giờ báo "đã xác nhận" khi backend chưa trả.
  Future<void> _send(PlanDevice d, DeviceActionOption opt) async {
    final n = _live[d.id];
    if (n == null || n.value.sending) return;
    if (_serverOffline.value) {
      n.value = n.value.copyWith(message: 'Mất kết nối máy chủ — chưa gửi được lệnh.', feedback: CommandFeedback.error);
      return;
    }
    n.value = n.value.copyWith(
      sending: true,
      pendingKey: opt.key,
      message: 'Đang gửi "${opt.label}"...',
      feedback: CommandFeedback.info,
    );
    var ok = false;
    try {
      ok = await _src.send(d.brand, d.id, opt);
    } catch (_) {
      ok = false;
    }
    if (!mounted || _live[d.id] != n) return;
    if (!ok) {
      n.value = n.value.copyWith(
        sending: false,
        pendingKey: null,
        message: 'Thiết bị không nhận lệnh "${opt.label}". Kiểm tra kết nối rồi thử lại.',
        feedback: CommandFeedback.error,
      );
      return;
    }
    n.value = n.value.copyWith(message: 'Đã gửi, đang chờ thiết bị xác nhận...');

    var confirmed = false;
    for (final delay in _src.confirmDelays) {
      await Future<void>.delayed(delay);
      if (!mounted || _live[d.id] != n) return;
      final s = await _src.fetchStatus(d.brand, d.id, true);
      if (!mounted || _live[d.id] != n) return;
      if (s != null) n.value = n.value.copyWith(status: s, readFailures: 0);
      if (statusConfirms(d.type, opt, s)) {
        confirmed = true;
        break;
      }
    }
    n.value = n.value.copyWith(
      sending: false,
      pendingKey: null,
      message: confirmed
          ? 'Đã xác nhận: ${opt.label}'
          : 'Đã gửi "${opt.label}" nhưng thiết bị chưa báo trạng thái mới.',
      feedback: confirmed ? CommandFeedback.success : CommandFeedback.warning,
    );
  }

  void _openControl(PlanDevice d) {
    final n = _live[d.id];
    if (n == null) return;
    // Bỏ thông báo của lần mở trước (trừ khi lệnh vẫn đang chạy).
    if (!n.value.sending && n.value.message != null) {
      n.value = n.value.copyWith(message: null, feedback: CommandFeedback.none);
    }
    // Mở bảng thì đọc ngay 1 nhịp — máy cho ăn không poll định kỳ.
    _readStatus(d);
    showDeviceControlSheet(
      context,
      device: d,
      live: n,
      serverOffline: _serverOffline,
      onAction: (opt) => _send(d, opt),
    );
  }

  // ------------------------------------------------------------ chế độ sửa
  void _startEdit() {
    final p = _plan;
    if (p == null) return;
    setState(() {
      _draft = p;
      _fitPlan = p;
    });
  }

  Future<void> _cancelEdit() async {
    if (!identical(_draft, _plan)) {
      final discard = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Bỏ thay đổi?'),
          content: const Text('Những gì bạn vừa sửa trên sơ đồ sẽ không được lưu.'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Sửa tiếp')),
            TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Bỏ')),
          ],
        ),
      );
      if (discard != true || !mounted) return;
    }
    setState(() {
      _draft = null;
      _fitPlan = _plan;
    });
  }

  Future<void> _save() async {
    final draft = _draft;
    if (draft == null || _saving) return;
    setState(() => _saving = true);
    final (saved, err) = await _src.savePlan(draft);
    if (!mounted) return;
    setState(() {
      _saving = false;
      if (saved != null) {
        _plan = saved;
        _fitPlan = saved;
        _draft = null;
      }
    });
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(err ?? 'Đã lưu sơ đồ cho cả nhà.'),
      backgroundColor: err != null ? Colors.redAccent : context.palette.primary,
    ));
  }

  void _setDraft(FloorPlan next, {bool refit = false}) {
    setState(() {
      _draft = next;
      if (refit) _fitPlan = next;
    });
  }

  PlanDevice? _deviceById(String id) {
    for (final d in _devices) {
      if (d.id == id) return d;
    }
    return null;
  }

  double get _zoom => math.max(1.0, _transform.value.getMaxScaleOnAxis());

  /// Tìm vật dưới ngón tay (px trong hệ tọa độ sơ đồ): thiết bị > cửa > phòng.
  _Target? _hitTest(Offset px) {
    final plan = _draft;
    final geo = _geometry;
    if (plan == null || geo == null) return null;
    final m = geo.toMeters(px);
    final deviceRadius = (DeviceMarker.iconDiameter / 2 + 8) / _zoom;
    for (final p in plan.devices.reversed) {
      final c = plan.deviceCenter(p.deviceId);
      if (c == null || _deviceById(p.deviceId) == null) continue;
      if ((geo.toPx(c) - px).distance <= deviceRadius) return _Target(_TargetKind.device, p.deviceId, c - m);
    }
    final doorRadius = 16 / _zoom;
    for (final d in plan.doors.reversed) {
      final r = plan.room(d.roomId);
      if (r == null) continue;
      final (a, b) = d.endpoints(r);
      if (_distToSegment(px, geo.toPx(a), geo.toPx(b)) <= doorRadius) return _Target(_TargetKind.door, d.id);
    }
    for (final r in plan.rooms.reversed) {
      if (r.rect.contains(m)) return _Target(_TargetKind.room, r.id, Offset(r.x, r.y) - m);
    }
    return null;
  }

  static double _distToSegment(Offset p, Offset a, Offset b) {
    final ab = b - a;
    final len2 = ab.dx * ab.dx + ab.dy * ab.dy;
    if (len2 == 0) return (p - a).distance;
    final t = (((p - a).dx * ab.dx + (p - a).dy * ab.dy) / len2).clamp(0.0, 1.0);
    return (p - (a + ab * t)).distance;
  }

  void _onEditPanStart(DragStartDetails e) => _drag = _hitTest(e.localPosition);

  void _onEditPanUpdate(DragUpdateDetails e) {
    final t = _drag;
    final plan = _draft;
    final geo = _geometry;
    if (t == null || plan == null || geo == null) return;
    final m = geo.toMeters(e.localPosition);
    switch (t.kind) {
      case _TargetKind.device:
        _setDraft(plan.moveDevice(t.id, m + t.grab));
      case _TargetKind.door:
        _setDraft(plan.slideDoor(t.id, m));
      case _TargetKind.room:
        _setDraft(plan.moveRoom(t.id, m + t.grab));
    }
  }

  void _onEditPanEnd([DragEndDetails? _]) {
    if (_drag?.kind == _TargetKind.room && _draft != null) _setDraft(_draft!, refit: true);
    _drag = null;
  }

  Future<void> _onEditTap(TapUpDetails e) async {
    final t = _hitTest(e.localPosition);
    final plan = _draft;
    if (t == null || plan == null) return;
    switch (t.kind) {
      case _TargetKind.device:
        final d = _deviceById(t.id);
        final remove = await showPlacedDeviceSheet(context, d?.name ?? t.id);
        if (remove == true && mounted && _draft != null) _setDraft(_draft!.removeDevice(t.id));
      case _TargetKind.door:
        final door = plan.doors.firstWhere((d) => d.id == t.id);
        final room = plan.room(door.roomId)!;
        final edit = await showDoorEditSheet(context, door, room);
        if (edit == null || !mounted || _draft == null) return;
        _setDraft(edit.delete ? _draft!.removeDoor(t.id) : _draft!.resizeDoor(t.id, edit.width!));
      case _TargetKind.room:
        final room = plan.room(t.id)!;
        final edit = await showRoomEditSheet(context, room);
        if (edit == null || !mounted || _draft == null) return;
        switch (edit) {
          case AddDoorEdit(:final wall):
            _setDraft(_draft!.addDoor(t.id, wall));
          case ResizeRoomEdit(:final width, :final depth):
            _setDraft(_draft!.resizeRoom(t.id, width: width, depth: depth), refit: true);
        }
    }
  }

  Future<void> _placeFromTray(PlanDevice d) async {
    final plan = _draft;
    if (plan == null) return;
    final roomId = await pickRoom(context, plan.rooms, d.name);
    if (roomId == null || !mounted || _draft == null) return;
    _setDraft(_draft!.placeDevice(d.id, roomId));
  }

  // ------------------------------------------------------------ giao diện
  FloorPlanColors _colors(AppPalette p) => FloorPlanColors(
        background: p.background,
        wall: p.textMain.withValues(alpha: 0.85),
        grid: p.outline,
        label: p.textMain,
        subLabel: p.textSub,
        door: Colors.orange,
        editAccent: p.primary,
        roomFills: [
          p.primary.withValues(alpha: 0.10),
          p.cyan.withValues(alpha: 0.16),
          p.purple.withValues(alpha: 0.12),
          p.success.withValues(alpha: 0.12),
        ],
      );

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final plan = _shown;
    return SafeArea(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _header(plan),
          ValueListenableBuilder<bool>(
            valueListenable: _serverOffline,
            builder: (_, offline, __) => offline
                ? Container(
                    key: const ValueKey('plan-offline-banner'),
                    color: Colors.redAccent,
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: const Text('Mất kết nối máy chủ. Đang thử lại...',
                        textAlign: TextAlign.center, style: TextStyle(color: Colors.white, fontSize: 12)),
                  )
                : const SizedBox.shrink(),
          ),
          if (plan != null && !plan.configured && !_editing) _notConfiguredBanner(),
          Expanded(
            child: plan == null
                ? _placeholder()
                : Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(20),
                      child: ColoredBox(color: p.background, child: _canvas(plan)),
                    ),
                  ),
          ),
          if (plan != null) ...[
            if (_editing) _editHint() else _legend(),
            _tray(plan),
          ],
          const SizedBox(height: 8),
        ],
      ),
    );
  }

  Widget _header(FloorPlan? plan) {
    final p = context.palette;
    final placed = plan == null ? 0 : _devices.where((d) => plan.placement(d.id) != null).length;
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 16, 12, 8),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(_editing ? 'Sửa sơ đồ' : 'Sơ đồ nhà',
                    style: TextStyle(color: p.textMain, fontSize: 24, fontWeight: FontWeight.bold)),
                Text(
                  _editing ? 'Kéo phòng, cửa, thiết bị • chạm để sửa' : '$placed/${_devices.length} thiết bị trên sơ đồ',
                  style: TextStyle(color: p.textSub, fontSize: 13),
                ),
              ],
            ),
          ),
          if (!_editing) ...[
            IconButton(
              tooltip: 'Về khung nhìn ban đầu',
              icon: Icon(Icons.fit_screen_outlined, color: p.textSub),
              onPressed: () => _transform.value = Matrix4.identity(),
            ),
            IconButton(
              tooltip: 'Tải lại',
              icon: Icon(Icons.refresh, color: p.textSub),
              onPressed: _load,
            ),
            if (_canEdit && _plan != null)
              TextButton.icon(
                key: const ValueKey('plan-edit'),
                onPressed: _startEdit,
                icon: const Icon(Icons.edit_outlined, size: 18),
                label: const Text('Sửa'),
              ),
          ] else ...[
            TextButton(onPressed: _saving ? null : _cancelEdit, child: const Text('Hủy')),
            const SizedBox(width: 4),
            FilledButton(
              key: const ValueKey('plan-save'),
              onPressed: _saving ? null : _save,
              child: _saving
                  ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Text('Lưu'),
            ),
          ],
        ],
      ),
    );
  }

  Widget _notConfiguredBanner() {
    final p = context.palette;
    return Container(
      key: const ValueKey('plan-not-configured'),
      margin: const EdgeInsets.fromLTRB(12, 0, 12, 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: Colors.orange.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.orange.withValues(alpha: 0.5)),
      ),
      child: Row(
        children: [
          const Icon(Icons.info_outline, color: Colors.orange, size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              _canEdit
                  ? 'Bố cục tạm: 2 phòng đúng kích thước nhưng chưa rõ vị trí tương đối và cửa. Bấm "Sửa" để kéo phòng, thêm cửa và đặt thiết bị.'
                  : 'Chủ nhà chưa cấu hình sơ đồ — vị trí phòng, cửa và thiết bị có thể chưa đúng thực tế.',
              style: TextStyle(color: p.textMain, fontSize: 12),
            ),
          ),
        ],
      ),
    );
  }

  Widget _placeholder() {
    final p = context.palette;
    if (_planError != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.map_outlined, size: 40, color: p.textSub),
            const SizedBox(height: 8),
            Text(_planError!, textAlign: TextAlign.center, style: TextStyle(color: p.textSub)),
            TextButton(onPressed: _load, child: const Text('Thử lại')),
          ],
        ),
      );
    }
    return Center(child: CircularProgressIndicator(color: p.primary));
  }

  Widget _canvas(FloorPlan plan) {
    return LayoutBuilder(builder: (context, c) {
      final avail = Size(math.max(1, c.maxWidth - 16), math.max(1, c.maxHeight - 16));
      final geo = PlanGeometry.fit(_fitPlan ?? plan, avail);
      _geometry = geo;
      return InteractiveViewer(
        transformationController: _transform,
        minScale: 1,
        maxScale: 5,
        // Sửa sơ đồ: 1 ngón dùng để KÉO VẬT, nên tạm tắt kéo/zoom khung nhìn
        // (zoom trước khi bấm Sửa vẫn được giữ nguyên).
        panEnabled: !_editing,
        scaleEnabled: !_editing,
        child: Center(
          child: SizedBox(
            key: const ValueKey('plan-canvas'),
            width: geo.size.width,
            height: geo.size.height,
            child: Stack(
              clipBehavior: Clip.none,
              children: [
                Positioned.fill(
                  child: RepaintBoundary(
                    child: CustomPaint(
                      painter: FloorPlanPainter(
                        rooms: plan.rooms,
                        doors: plan.doors,
                        geometry: geo,
                        colors: _colors(context.palette),
                        editing: _editing,
                      ),
                    ),
                  ),
                ),
                for (final d in _devices) ..._marker(plan, geo, d),
                if (_editing)
                  Positioned.fill(
                    child: GestureDetector(
                      key: const ValueKey('plan-edit-layer'),
                      behavior: HitTestBehavior.opaque,
                      // Vật được chọn theo chỗ NGÓN TAY CHẠM XUỐNG, không phải chỗ
                      // cử chỉ được nhận là kéo (lệch ~36px) — không thì kéo nhanh
                      // 1 icon nhỏ sẽ trượt sang kéo cả phòng.
                      dragStartBehavior: DragStartBehavior.down,
                      onTapUp: _onEditTap,
                      onPanStart: _onEditPanStart,
                      onPanUpdate: _onEditPanUpdate,
                      onPanEnd: _onEditPanEnd,
                      onPanCancel: _onEditPanEnd,
                    ),
                  ),
              ],
            ),
          ),
        ),
      );
    });
  }

  /// Icon đặt sao cho TÂM vòng tròn trùng tọa độ thiết bị, và giữ nguyên kích
  /// thước trên màn hình khi zoom (thu theo 1/zoom quanh đúng tâm đó) — vị trí
  /// vẫn đi theo sơ đồ nên không bao giờ lệch khỏi phòng.
  List<Widget> _marker(FloorPlan plan, PlanGeometry geo, PlanDevice d) {
    final c = plan.deviceCenter(d.id);
    final live = _live[d.id];
    if (c == null || live == null) return const [];
    final px = geo.toPx(c);
    const half = DeviceMarker.iconDiameter / 2;
    return [
      Positioned(
        key: ValueKey('plan-marker-${d.id}'),
        left: px.dx - DeviceMarker.width / 2,
        top: px.dy - half,
        child: RepaintBoundary(
          child: AnimatedBuilder(
            animation: _transform,
            builder: (_, child) => Transform.scale(
              scale: 1 / _zoom,
              alignment: Alignment.topCenter,
              origin: const Offset(0, half),
              child: child,
            ),
            child: DeviceMarker(
              device: d,
              live: live,
              editing: _editing,
              onTap: _editing ? null : () => _openControl(d),
            ),
          ),
        ),
      ),
    ];
  }

  Widget _legend() {
    final p = context.palette;
    Widget item(Color fill, Color border, String label) => Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 10,
              height: 10,
              decoration: BoxDecoration(color: fill, shape: BoxShape.circle, border: Border.all(color: border, width: 1.5)),
            ),
            const SizedBox(width: 4),
            Text(label, style: TextStyle(color: p.textSub, fontSize: 11)),
          ],
        );
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
      child: Wrap(
        alignment: WrapAlignment.center,
        spacing: 14,
        runSpacing: 4,
        children: [
          item(p.cyan, p.cyan, 'Đang bật / mở'),
          item(p.card, p.cyan, 'Tắt / đóng'),
          item(p.card, p.primary, 'Đang xử lý'),
          item(p.card, offlineColor, 'Mất kết nối'),
        ],
      ),
    );
  }

  Widget _editHint() {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
      child: Text(
        'Chạm phòng: thêm cửa / sửa kích thước • Chạm cửa: đổi bề rộng / xóa • Chạm thiết bị: bỏ khỏi sơ đồ',
        textAlign: TextAlign.center,
        style: TextStyle(color: p.textSub, fontSize: 11),
      ),
    );
  }

  /// Thiết bị chưa có vị trí: vẫn chạm để điều khiển được (không thiết bị nào
  /// bị "mất" chỉ vì chưa ai đặt nó lên sơ đồ); khi sửa thì chạm để đặt.
  Widget _tray(FloorPlan plan) {
    final p = context.palette;
    final unplaced = _devices.where((d) => plan.placement(d.id) == null).toList();
    if (unplaced.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20),
            child: Text(
              _editing ? 'Chạm để đặt lên sơ đồ' : 'Chưa đặt trên sơ đồ',
              style: TextStyle(color: p.textSub, fontSize: 12),
            ),
          ),
          const SizedBox(height: 4),
          SizedBox(
            height: 40,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 16),
              children: [
                for (final d in unplaced)
                  Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: ActionChip(
                      key: ValueKey('plan-tray-${d.id}'),
                      avatar: Icon(_editing ? Icons.add_location_alt_outlined : deviceIconOf(d.type),
                          size: 16, color: deviceAccentOf(context, d.type)),
                      label: Text(d.name, style: TextStyle(color: p.textMain, fontSize: 12)),
                      onPressed: () => _editing ? _placeFromTray(d) : _openControl(d),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
