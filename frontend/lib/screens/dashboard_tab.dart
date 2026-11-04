import 'dart:async'; // Bắt buộc để dùng Timer
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:http/http.dart' as http;
import '../theme/app_colors.dart';
import '../core/auth_service.dart';
import '../core/avatar.dart';
import 'profile_screen.dart';
import '../core/config.dart';
import '../core/device_api.dart';
import '../core/device_order.dart';
import '../core/device_type.dart';
import '../core/scene_api.dart';
import '../core/zone_groups.dart';
import 'scene_editor_screen.dart';
import '../core/shortcut_service.dart';
import '../core/shortcut_handler.dart';
import '../core/widget_service.dart';
import 'admin_screen.dart';

class DashboardTab extends StatefulWidget {
  /// Tab Home có đang hiển thị không (IndexedStack giữ tab sống kể cả khi ẩn).
  /// Dùng để tạm dừng poll trạng thái khi người dùng ở tab khác.
  final bool isVisible;

  /// Hồ sơ người dùng trong nhà (vai, khu được cấp) — do AuthGate truyền
  /// xuống để không màn nào phải gọi lại /api/me.
  final HouseholdProfile profile;

  /// Gọi khi bấm Đăng xuất.
  final Future<void> Function()? onSignOut;

  /// Gọi khi người dùng sửa hồ sơ (tên/màu avatar) ở màn Hồ sơ.
  final ValueChanged<HouseholdProfile>? onProfileChanged;

  const DashboardTab({
    super.key,
    this.isVisible = true,
    this.profile = HouseholdProfile.openHouse,
    this.onSignOut,
    this.onProfileChanged,
  });

  @override
  State<DashboardTab> createState() => _DashboardTabState();
}

class _DashboardTabState extends State<DashboardTab> with WidgetsBindingObserver {
  final String baseUrl = AppConfig.baseUrl;
  List<dynamic> devices = [];
  bool isLoading = true;
  bool isOffline = false; // Cờ theo dõi trạng thái mạng
  bool isWaking = false;  // Đang đánh thức server (Render free-tier ngủ -> cold start)
  Timer? _retryTimer;     // Bộ đếm giờ tự thử lại
  bool _appActive = true; // App đang ở foreground? (pause poll khi vào nền)
  List<Scene> _scenes = [];
  final Set<int> _runningScenes = {};
  String _zoneFilter = allZonesKey;
  // Thứ tự khu theo backend (zones.sort_order), lấy TRƯỚC khi áp thứ tự kéo-thả.
  List<String> _zoneOrder = [];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _bootstrap();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Vào nền -> dừng poll (tiết kiệm pin/mạng); trở lại -> poll tiếp ngay.
    final active = state == AppLifecycleState.resumed;
    if (mounted && active != _appActive) {
      setState(() => _appActive = active);
    }
  }

  // Đánh thức server trước (Render free-tier ngủ sau ~15 phút, cold start 30-50s),
  // hiển thị trạng thái "đang đánh thức" thay vì treo im lặng, rồi mới tải thiết bị.
  Future<void> _bootstrap() async {
    setState(() => isWaking = true);
    try {
      await http.get(Uri.parse('$baseUrl/health')).timeout(AppConfig.healthTimeout);
    } catch (_) {
      // Bỏ qua: nếu thất bại, fetchDevices bên dưới sẽ xử lý offline.
    }
    if (!mounted) return;
    setState(() => isWaking = false);
    fetchDevices();
  }

  /// Tên chào. Ưu tiên tên hiển thị, rồi phần trước @ của email; chưa đăng
  /// nhập (backend chạy xác thực TẮT) thì giữ lời chào chung.
  String get _greetingName => '${widget.profile.friendlyName ?? 'Nhà mình'} 🖖';

  Future<void> _openProfile() async {
    final updated = await Navigator.of(context).push<HouseholdProfile>(MaterialPageRoute(
      builder: (_) => ProfileScreen(profile: widget.profile, onSignOut: widget.onSignOut),
    ));
    if (updated != null) widget.onProfileChanged?.call(updated);
  }

  /// Nút tài khoản: hiện vai + khu được cấp, và lối đăng xuất. Không có nó thì
  /// người dùng không có cách nào thoát tài khoản trong app.
  Widget _accountMenu() {
    final p = widget.profile;
    const roleLabel = {
      'owner': 'Chủ nhà',
      'adult': 'Người lớn',
      'kid': 'Trẻ em',
      'guest': 'Khách',
    };
    return PopupMenuButton<String>(
      tooltip: 'Tài khoản',
      color: context.palette.surface,
      onSelected: (v) {
        if (v == 'signout') widget.onSignOut?.call();
        if (v == 'profile') _openProfile();
        if (v == 'admin') {
          Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => AdminScreen(profile: p),
          ));
        }
      },
      itemBuilder: (_) => [
        PopupMenuItem<String>(
          enabled: false,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(p.email.isEmpty ? 'Chưa đăng nhập' : p.email,
                  style: TextStyle(color: context.palette.textMain, fontSize: 13)),
              const SizedBox(height: 2),
              Text(
                p.scopeLabel,
                style: TextStyle(color: context.palette.textSub, fontSize: 12),
              ),
            ],
          ),
        ),
        const PopupMenuDivider(),
        PopupMenuItem<String>(
          value: 'profile',
          child: Row(
            children: [
              Icon(Icons.person_outline, size: 18, color: context.palette.textSub),
              const SizedBox(width: 10),
              Text('Hồ sơ & giao diện', style: TextStyle(color: context.palette.textMain)),
            ],
          ),
        ),
        // Chỉ chủ nhà mới có mục Quản trị — người khác bấm vào cũng chỉ nhận
        // 403 từ API, hiện nút ra là mời người ta vào ngõ cụt.
        // Menu LUÔN hiện kể cả khi chưa bật đăng nhập: chủ nhà cần vào đây
        // chia phòng TRƯỚC, rồi mới bật xác thực — ngược lại thì không có
        // khu nào để cấp cho trẻ em lúc duyệt.
        if (p.canAdmin)
          PopupMenuItem<String>(
            value: 'admin',
            child: Row(
              children: [
                Icon(Icons.admin_panel_settings_outlined, size: 18, color: context.palette.textSub),
                const SizedBox(width: 10),
                Text('Quản trị nhà', style: TextStyle(color: context.palette.textMain)),
              ],
            ),
          ),
        // Đăng xuất chỉ có nghĩa khi thật sự có đăng nhập.
        if (widget.onSignOut != null)
          PopupMenuItem<String>(
            value: 'signout',
            child: Row(
              children: [
                Icon(Icons.logout, size: 18, color: context.palette.textSub),
                const SizedBox(width: 10),
                Text('Đăng xuất', style: TextStyle(color: context.palette.textMain)),
              ],
            ),
          ),
      ],
      child: Container(
        padding: const EdgeInsets.fromLTRB(6, 6, 12, 6),
        decoration: BoxDecoration(
          color: context.palette.surface,
          borderRadius: BorderRadius.circular(16),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            UserAvatar(profile: p, size: 30),
            const SizedBox(width: 8),
            Text(
              roleLabel[p.role] ?? 'Tài khoản',
              style: TextStyle(color: context.palette.textMain, fontSize: 13),
            ),
            const SizedBox(width: 4),
            Icon(Icons.expand_more, size: 16, color: context.palette.textSub),
          ],
        ),
      ),
    );
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _retryTimer?.cancel(); // Tắt timer khi thoát màn hình
    super.dispose();
  }

  // Card báo trạng thái THẬT (từ poll) về đây để header đếm "Đang bật" đúng —
  // trước đây chỉ đếm is_active tĩnh từ /api/devices nên sai khi thiết bị
  // được bật/tắt từ remote vật lý hoặc app khác.
  void _onDeviceStatusChanged(dynamic device, bool isOn) {
    if (device['is_active'] == isOn) return;
    setState(() => device['is_active'] = isOn);
  }

  // 1. HÀM LẤY DỮ LIỆU ĐƯỢC NÂNG CẤP (Có Timeout và Auto-Retry)
  Future<void> fetchDevices() async {
    try {
      // Đi qua DeviceApi để CÓ header xác thực. Trước đây chỗ này gọi http.get
      // thẳng nên là call site duy nhất thiếu token — bật xác thực lên là
      // dashboard trống trơn trong khi mọi thứ khác vẫn chạy.
      final data = await DeviceApi.fetchDevices();
      if (data == null) {
        _handleOffline();
        return;
      }
      // Sắp theo thứ tự người dùng đã kéo-thả (lưu cục bộ); thiết bị mới xuống cuối.
      final order = await DeviceOrder.load();
      // Kịch bản tải kèm; lỗi thì giữ danh sách cũ (không làm hỏng màn hình chính).
      final scenes = await SceneApi.fetchScenes();
      if (!mounted) return;
      setState(() {
        _zoneOrder = <String>{for (final d in data) zoneKeyOf(d)}.toList();
        devices = DeviceOrder.apply(List<dynamic>.from(data), order);
        if (scenes != null) _scenes = scenes;
        // Khu đang lọc không còn thiết bị nào (bị xóa/chuyển) -> về "Tất cả".
        if (_zoneFilter != allZonesKey && !devices.any((d) => zoneKeyOf(d) == _zoneFilter)) {
          _zoneFilter = allZonesKey;
        }
        isLoading = false;
        isOffline = false; // Đã có mạng
      });
      _retryTimer?.cancel(); // Tắt bộ thử lại
      WidgetService.refreshAll(); // Đồng bộ trạng thái lên Home Screen Widget
    } catch (e) {
      _handleOffline();
    }
  }

  // 2. LOGIC TỰ ĐỘNG THỬ LẠI SAU MỖI 5 GIÂY
  void _handleOffline() {
    if (!mounted) return;
    setState(() {
      isLoading = false;
      isOffline = true;
    });

    _retryTimer?.cancel();
    _retryTimer = Timer(const Duration(seconds: 5), () {
      debugPrint("Đang thử kết nối lại...");
      fetchDevices(); // Tự động gọi lại chính nó
    });
  }

  // 3. LOGIC ĐIỀU KHIỂN NÂNG CẤP: Báo lỗi ngay nếu rớt mạng
  Future<void> _toggleDeviceState(dynamic device, bool value) async {
    if (isOffline) {
      _showErrorSnackBar("Không thể điều khiển khi mất kết nối!");
      return;
    }

    setState(() => device['is_active'] = value);
    final action = value ? "on" : "off";
    final brand = device['brand'].toString().toLowerCase();
    final dId = device['id'].toString();

    // Dùng DeviceApi (chung baseUrl/timeout) — trả false nếu thiết bị không nhận lệnh.
    final ok = await DeviceApi.sendAction(brand, dId, action);
    if (!mounted) return;
    if (!ok) {
      setState(() => device['is_active'] = !value); // Trả lại công tắc
      _showErrorSnackBar("Lỗi kết nối. Vui lòng thử lại!");
    }
  }

  void _showErrorSnackBar(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), backgroundColor: Colors.redAccent, duration: const Duration(seconds: 2)),
    );
  }

  // ---------------- Kịch bản ----------------
  Future<void> _runScene(Scene scene) async {
    if (_runningScenes.contains(scene.id)) return;
    // Kịch bản có MỞ CỬA: xác nhận trước — chạm nhầm 1 cái là cửa nhà mở toang.
    if (sceneOpensDoor(scene, devices)) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text('Chạy "${scene.name}"?'),
          content: const Text('Kịch bản này sẽ MỞ CỬA CUỐN.'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Hủy')),
            TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Chạy')),
          ],
        ),
      );
      if (ok != true || !mounted) return;
    }
    setState(() => _runningScenes.add(scene.id));
    final (result, err) = await SceneApi.run(scene.id);
    if (!mounted) return;
    setState(() => _runningScenes.remove(scene.id));
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(err ?? '${scene.name}: ${result!.summary}'),
      backgroundColor: (err != null || result!.failed > 0) ? Colors.redAccent : context.palette.primary,
    ));
  }

  Future<void> _editScene([Scene? scene]) async {
    final changed = await Navigator.of(context).push<bool>(MaterialPageRoute(
      builder: (_) => SceneEditorScreen(scene: scene, devices: devices),
    ));
    if (changed == true) fetchDevices();
  }

  Widget _scenesRow() {
    final p = context.palette;
    final canEdit = widget.profile.canEditScenes;
    return SizedBox(
      height: 86,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 24),
        children: [
          for (final sc in _scenes)
            Padding(
              padding: const EdgeInsets.only(right: 12),
              child: InkWell(
                borderRadius: BorderRadius.circular(18),
                onTap: () => _runScene(sc),
                onLongPress: canEdit ? () => _editScene(sc) : null,
                child: Container(
                  width: 104,
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: p.card,
                    borderRadius: BorderRadius.circular(18),
                    border: Border.all(color: p.outline),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      _runningScenes.contains(sc.id)
                          ? SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2, color: p.primary))
                          : Icon(sceneIconOf(sc), color: p.primary, size: 24),
                      Text(sc.name, maxLines: 2, overflow: TextOverflow.ellipsis,
                          style: TextStyle(color: p.textMain, fontSize: 12, fontWeight: FontWeight.w600)),
                    ],
                  ),
                ),
              ),
            ),
          if (canEdit)
            InkWell(
              borderRadius: BorderRadius.circular(18),
              onTap: devices.isEmpty ? null : () => _editScene(),
              child: Container(
                width: 86,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(18),
                  border: Border.all(color: p.primary.withValues(alpha: 0.4)),
                ),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(Icons.add, color: p.primary),
                    Text('Kịch bản', style: TextStyle(color: p.primary, fontSize: 12)),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }

  // ---------------- Nhà theo khu ----------------
  Widget _zoneChips(List<ZoneGroup> groups) {
    final p = context.palette;
    Widget chip(String key, String label, {bool shared = false}) {
      final selected = _zoneFilter == key;
      return Padding(
        padding: const EdgeInsets.only(right: 8),
        child: ChoiceChip(
          avatar: shared ? Icon(Icons.home_rounded, size: 16, color: selected ? Colors.white : p.primary) : null,
          label: Text(label),
          selected: selected,
          showCheckmark: false,
          selectedColor: p.primary,
          labelStyle: TextStyle(color: selected ? Colors.white : p.textMain, fontSize: 12),
          onSelected: (_) => setState(() => _zoneFilter = key),
        ),
      );
    }

    return SizedBox(
      height: 44,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 24),
        children: [
          chip(allZonesKey, 'Tất cả ${devices.length}'),
          for (final g in groups) chip(g.key, '${g.name} ${g.on}/${g.total}', shared: g.shared),
        ],
      ),
    );
  }

  // Kéo-thả đổi thứ tự thiết bị (chỉ ảnh hưởng hiển thị, lưu cục bộ SharedPreferences).
  // Dùng onReorderItem: newIndex ĐÃ được điều chỉnh cho item bị gỡ tại oldIndex.
  void _onReorder(int oldIndex, int newIndex) {
    setState(() {
      final item = devices.removeAt(oldIndex);
      devices.insert(newIndex, item);
    });
    DeviceOrder.save([for (final d in devices) '${d['id']}']);
  }

  @override
  Widget build(BuildContext context) {
    int activeCount = devices.where((d) => d['is_active'] == true).length;
    final zoneGroups = zoneGroupsOf(devices, _zoneOrder);
    // Kéo-thả chỉ khi xem "Tất cả": thứ tự lưu là thứ tự TOÀN BỘ danh sách.
    final canReorder = _zoneFilter == allZonesKey;
    final shown = devicesInZone(devices, _zoneFilter);

    return SafeArea(
      child: Column(
        children: [
          // THANH CẢNH BÁO MẤT MẠNG KẾT DÍNH (Sticky Banner)
          if (isOffline)
            Container(
              width: double.infinity,
              color: Colors.redAccent,
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: const Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  SizedBox(width: 12, height: 12, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2)),
                  SizedBox(width: 8),
                  Text("Mất kết nối máy chủ. Đang thử lại...", style: TextStyle(color: Colors.white, fontSize: 12)),
                ],
              ),
            ).animate().fade().slideY(),

          Expanded(
            child: isLoading && devices.isEmpty
            ? Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    CircularProgressIndicator(color: context.palette.primary),
                    if (isWaking) ...[
                      const SizedBox(height: 16),
                      Text(
                        "Đang đánh thức máy chủ...",
                        style: TextStyle(color: context.palette.textSub, fontSize: 13),
                      ),
                    ],
                  ],
                ),
              )
            // 4. KÉO ĐỂ REFRESH (Pull to Refresh)
            : RefreshIndicator(
              onRefresh: fetchDevices,
              color: context.palette.primary,
              backgroundColor: context.palette.surface,
              child: CustomScrollView(
                physics: const AlwaysScrollableScrollPhysics(), // Ép cho phép cuộn để Refresh kể cả khi danh sách ngắn
                slivers: [
                  SliverToBoxAdapter(
                    child: Padding(
                      padding: const EdgeInsets.all(24.0),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text("Welcome Home,", style: TextStyle(color: context.palette.textSub, fontSize: 14)),
                                    Text(
                                      _greetingName,
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style: TextStyle(color: context.palette.textMain, fontSize: 28, fontWeight: FontWeight.bold),
                                    ),
                                  ],
                                ),
                              ),
                              _accountMenu(),
                            ],
                          ),
                          const SizedBox(height: 24),
                          Container(
                            padding: const EdgeInsets.all(20),
                            decoration: BoxDecoration(
                              gradient: context.palette.primaryGradient,
                              borderRadius: BorderRadius.circular(24),
                              boxShadow: [BoxShadow(color: context.palette.primary.withValues(alpha: 0.3), blurRadius: 20, offset: const Offset(0, 8))],
                            ),
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                _buildStat("Thiết bị", "${devices.length}", Icons.devices_other),
                                _buildStat("Đang bật", "$activeCount", Icons.bolt),
                                _buildStat("Khu vực", "${zoneGroups.where((g) => g.key != unassignedKey).length}", Icons.meeting_room),
                              ],
                            ),
                          ).animate().fade(duration: 500.ms).slideY(begin: 0.2),
                        ],
                      ),
                    ),
                  ),

                  if (devices.isEmpty && !isLoading)
                    SliverFillRemaining(
                      child: Center(child: Text("Không có dữ liệu thiết bị", style: TextStyle(color: context.palette.textSub))),
                    )
                  else ...[
                    if (_scenes.isNotEmpty || widget.profile.canEditScenes)
                      SliverToBoxAdapter(
                        child: Padding(padding: const EdgeInsets.only(bottom: 16), child: _scenesRow()),
                      ),
                    if (zoneGroups.length > 1)
                      SliverToBoxAdapter(
                        child: Padding(padding: const EdgeInsets.only(bottom: 8), child: _zoneChips(zoneGroups)),
                      ),
                    if (canReorder && devices.length > 1)
                      SliverToBoxAdapter(
                        child: Padding(
                          padding: const EdgeInsets.only(left: 24, right: 24, bottom: 4),
                          child: Row(
                            children: [
                              Icon(Icons.drag_indicator, size: 14, color: context.palette.textSub),
                              const SizedBox(width: 4),
                              Text("Kéo biểu tượng ⋮⋮ bên phải thẻ để sắp xếp", style: TextStyle(color: context.palette.textSub, fontSize: 11)),
                            ],
                          ),
                        ),
                      ),
                    SliverReorderableList(
                      itemCount: shown.length,
                      onReorderItem: _onReorder,
                      // Thẻ nổi lên gọn gàng (bo góc + đổ bóng) khi đang kéo.
                      proxyDecorator: (child, index, animation) => Material(
                        color: Colors.transparent,
                        elevation: 8,
                        shadowColor: Colors.black54,
                        borderRadius: BorderRadius.circular(24),
                        child: child,
                      ),
                      itemBuilder: (context, index) {
                        final device = shown[index];
                        // Key ổn định theo id (PK) để list giữ đúng state card khi đổi chỗ.
                        // CHỈ kéo bằng tay cầm riêng (drag handle) — không bọc cả thẻ, tránh
                        // xung đột cử chỉ với nút/switch bên trong (gây message lỗi khi nhấn giữ).
                        return Padding(
                          key: ValueKey('${device['id']}'),
                          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 8),
                          child: SmartDeviceCard(
                            device: device,
                            baseUrl: baseUrl,
                            isOffline: isOffline, // Truyền trạng thái mạng vào Card
                            // Poll trạng thái CHỈ khi tab Home hiển thị + app ở foreground.
                            pollingEnabled: widget.isVisible && _appActive,
                            onToggle: (val) => _toggleDeviceState(device, val),
                            onStatusChanged: (isOn) => _onDeviceStatusChanged(device, isOn),
                            dragHandle: canReorder
                                ? ReorderableDragStartListener(
                                    index: index,
                                    child: Padding(
                                      padding: const EdgeInsets.all(4),
                                      child: Icon(Icons.drag_indicator, color: context.palette.textSub, size: 22),
                                    ),
                                  )
                                : null,
                          ),
                        );
                      },
                    ),
                  ],
                  const SliverToBoxAdapter(child: SizedBox(height: 100)),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildStat(String label, String value, IconData icon) {
    return Column(
      children: [
        Icon(icon, color: Colors.white70, size: 20),
        const SizedBox(height: 8),
        Text(value, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
        Text(label, style: const TextStyle(color: Colors.white70, fontSize: 12)),
      ],
    );
  }
}

// COMPONENT: THẺ THIẾT BỊ
class SmartDeviceCard extends StatefulWidget {
  final dynamic device;
  final String baseUrl;
  final bool isOffline;
  final bool pollingEnabled; // false khi tab ẩn / app ở nền -> dừng poll 6s
  final Function(bool) onToggle;
  final Function(bool)? onStatusChanged; // báo trạng thái THẬT về parent (đếm "Đang bật")
  final Widget? dragHandle; // tay cầm kéo-thả (null nếu không cho sắp xếp)

  const SmartDeviceCard({
    super.key,
    required this.device,
    required this.baseUrl,
    required this.isOffline,
    required this.onToggle,
    this.pollingEnabled = true,
    this.onStatusChanged,
    this.dragHandle,
  });

  @override
  State<SmartDeviceCard> createState() => _SmartDeviceCardState();
}

class _SmartDeviceCardState extends State<SmartDeviceCard> {
  Map<String, dynamic>? _status; // trạng thái THẬT từ backend (nếu có)
  bool _sending = false;         // đang gửi lệnh -> chặn double-tap
  String? _pendingMode;          // mode vừa bấm (tô sáng lạc quan trước khi có trạng thái thật)
  DateTime? _pendingSince;       // thời điểm set _pendingMode (để timeout tránh kẹt highlight)
  Timer? _pollTimer;             // tự động poll trạng thái định kỳ
  String? _lastShortcutIcon;     // icon shortcut đã đẩy gần nhất (tránh gọi native lặp lại)

  // Giữ tô sáng lạc quan tối đa 10s: nếu cloud vẫn chưa xác nhận thì thôi giữ
  // (tránh kẹt highlight sai khi lệnh thật sự không ăn).
  static const Duration _pendingTimeout = Duration(seconds: 10);

  String get _brand => widget.device['brand'].toString().toLowerCase();
  String get _id => widget.device['id'].toString();
  String get _name => widget.device['name'].toString();

  DeviceType get _type => deviceTypeOf(_name, category: widget.device['category'] as String?);
  bool get _isAirPurifier => _type == DeviceType.airPurifier;
  bool get _isFeeder => _type == DeviceType.feeder;
  bool get _isCurtain => _type == DeviceType.curtain;
  bool get _isSwitch => _type == DeviceType.powerSwitch;

  // Máy bơm cũng poll: biết nó ĐANG CHẠY hay không là thông tin quan trọng
  // (có thể bị bật/tắt từ app Tuya hay nút vật lý).
  bool get _needsStatus => _isAirPurifier || _isCurtain || _isSwitch;

  @override
  void initState() {
    super.initState();
    // Máy lọc & cửa: poll trạng thái thật 6s. Máy cho ăn chỉ đọc khi hiện lên
    // + sau khi bấm cho ăn (trạng thái ít đổi, tiết kiệm quota API Tuya).
    if (_needsStatus || _isFeeder) _refreshStatus();
    if (_needsStatus) _setPolling(widget.pollingEnabled);
  }

  @override
  void didUpdateWidget(covariant SmartDeviceCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    // Tab ẩn / app vào nền -> dừng poll; hiển thị lại -> refresh ngay + poll tiếp.
    if (_isFeeder && widget.pollingEnabled && !oldWidget.pollingEnabled) _refreshStatus();
    if (_needsStatus && widget.pollingEnabled != oldWidget.pollingEnabled) {
      if (widget.pollingEnabled) _refreshStatus();
      _setPolling(widget.pollingEnabled);
    }
  }

  // Bật/tắt vòng poll trạng thái 6s.
  void _setPolling(bool enabled) {
    _pollTimer?.cancel();
    _pollTimer = enabled
        ? Timer.periodic(const Duration(seconds: 6), (_) => _refreshStatus())
        : null;
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    super.dispose();
  }

  /// Suy ra "modeValue tương đương" từ trạng thái THẬT, để đối chiếu với
  /// _pendingMode (mode vừa bấm). Trả null nếu không xác định được.
  String? _currentModeValue(Map<String, dynamic> s) {
    if (_isCurtain) {
      final ds = '${s['door_state'] ?? ''}'.toLowerCase();
      return const {
        'open': 'open',
        'opening': 'open',
        'closed': 'close',
        'closing': 'close',
        'stopped': 'stop',
      }[ds];
    }
    if (_isAirPurifier) {
      // PurifierStep.mode: off/on -> null; low->'1', med->'2', high->'3', auto, sleep.
      return PurifierCycle.steps[PurifierCycle.indexFromStatus(s)].mode;
    }
    return null;
  }

  Future<void> _refreshStatus({bool fresh = false}) async {
    if (widget.isOffline || !mounted) return;
    final s = await DeviceApi.fetchStatus(_brand, _id, fresh: fresh);
    if (!mounted) return;
    setState(() {
      if (s != null) _status = s;
      // Chỉ bỏ tô sáng lạc quan khi trạng thái thật ĐÃ KHỚP mode vừa bấm
      // (cloud xác nhận), hoặc đã quá hạn chờ. Nếu chưa khớp -> GIỮ highlight
      // để không nhảy về mode cũ khi cloud chưa kịp propagate.
      if (_pendingMode != null) {
        final matched = s != null && _currentModeValue(s) == _pendingMode;
        final expired = _pendingSince != null &&
            DateTime.now().difference(_pendingSince!) >= _pendingTimeout;
        if (matched || expired) {
          _pendingMode = null;
          _pendingSince = null;
        }
      }
    });
    // Đồng bộ icon shortcut theo trạng thái THẬT vừa poll được -> icon hội tụ đúng
    // cả khi cửa/quạt bị điều khiển từ remote vật lý / app khác (khi app đang mở).
    if (s != null) _syncShortcutIcon(s);
    // Báo trạng thái ON/OFF thật về parent để header đếm "Đang bật" chính xác.
    if (s != null) {
      widget.onStatusChanged?.call('${s['status']}'.toUpperCase() == 'ON');
    }
  }

  /// Đẩy icon shortcut (nếu đã pin) cho khớp trạng thái THẬT. Gọi updateShortcut
  /// cho id chưa pin là no-op an toàn ở native (ShortcutManagerCompat chỉ cập nhật
  /// shortcut đang tồn tại) nên không cần lưu danh sách shortcut đã tạo. Chỉ gọi
  /// khi icon thật sự đổi để tránh gọi native mỗi nhịp poll.
  void _syncShortcutIcon(Map<String, dynamic> s) {
    String type;
    String iconRes;
    String label = _name;
    if (_isCurtain) {
      final ds = '${s['door_state'] ?? ''}'.toLowerCase();
      if (ds.isEmpty || ds == 'unknown') return;
      type = ShortcutType.doorToggle;
      iconRes = ShortcutIcons.door(ds);
    } else if (_isAirPurifier) {
      final step = PurifierCycle.steps[PurifierCycle.indexFromStatus(s)];
      type = ShortcutType.purifierCycle;
      iconRes = ShortcutIcons.purifier(step.key);
      label = '$_name • ${step.label}';
    } else {
      return;
    }
    if (iconRes == _lastShortcutIcon) return;
    _lastShortcutIcon = iconRes;
    final action = ShortcutAction(type: type, brand: _brand, deviceId: _id, deviceName: _name);
    ShortcutService.instance.updateShortcutIcon(action, label: label, iconRes: iconRes);
  }

  /// Sau khi gửi lệnh: poll lại nhiều nhịp (đọc FRESH bỏ cache) tới khi trạng
  /// thái thật khớp mode vừa bấm, bắt kịp độ trễ propagation của cloud.
  Future<void> _refreshAfterCommand() async {
    final hadPending = _pendingMode != null;
    const delays = [
      Duration(milliseconds: 700),
      Duration(milliseconds: 1300),
      Duration(seconds: 2),
      Duration(seconds: 3),
    ];
    for (var i = 0; i < delays.length; i++) {
      await Future.delayed(delays[i]);
      if (!mounted) return;
      await _refreshStatus(fresh: true);
      // Có pending: dừng sớm khi cloud đã xác nhận (reconcile xong).
      if (hadPending && _pendingMode == null) return;
      // Không pending (switch on/off): chỉ cần vài nhịp, tránh khóa switch quá lâu.
      if (!hadPending && i >= 1) return;
    }
  }

  void _snack(String msg, Color color) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), backgroundColor: color, duration: const Duration(seconds: 2)),
    );
  }

  Future<void> _sendMode(String label, String modeValue) async {
    if (widget.isOffline) {
      _snack("Không thể điều khiển khi mất kết nối!", Colors.redAccent);
      return;
    }
    if (_sending) return; // chặn double-tap: đang gửi lệnh trước đó

    // Tô sáng ngay nút vừa bấm (lạc quan) để phản hồi tức thì, không đợi round-trip.
    setState(() {
      _sending = true;
      _pendingMode = modeValue;
      _pendingSince = DateTime.now();
    });
    try {
      final ok = await DeviceApi.sendMode(_brand, _id, modeValue);
      if (!mounted) return;
      if (ok) {
        _snack('Đã chọn: $label', context.palette.primary);
        _refreshAfterCommand(); // reconcile trạng thái thật (có lặp lại vài nhịp)
      } else {
        setState(() {
          _pendingMode = null; // bỏ tô sáng lạc quan khi lệnh thất bại
          _pendingSince = null;
        });
        _snack("Lỗi kết nối tới thiết bị!", Colors.redAccent);
      }
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  // Tạo icon shortcut rời trên home screen cho thiết bị này.
  Future<void> _createShortcut(String type, String label, String iconRes) async {
    final action = ShortcutAction(type: type, brand: _brand, deviceId: _id, deviceName: _name);
    final ok = await ShortcutService.instance.pinShortcut(action, label: label, iconRes: iconRes);
    if (!mounted) return;
    _snack(
      ok ? 'Đã yêu cầu tạo icon "$label". Kiểm tra màn hình chính.' : 'Thiết bị/OS chưa hỗ trợ tạo icon rời.',
      ok ? Colors.green : Colors.orangeAccent,
    );
  }

  Widget _buildModeButton(String label, String modeValue, Color glowColor, {bool selected = false, bool enabled = true}) {
    return ActionChip(
      label: Text(
        label,
        style: TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w600,
          color: selected ? Colors.white : (enabled ? context.palette.textMain : context.palette.textSub),
        ),
      ),
      backgroundColor: selected ? glowColor : context.palette.surface,
      side: BorderSide(color: glowColor.withValues(alpha: selected ? 0.9 : 0.3), width: 1),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      onPressed: enabled ? () => _sendMode(label, modeValue) : null,
    );
  }

  Widget _buildShortcutButton(String type, String label, String iconRes, Color glowColor) {
    return ActionChip(
      avatar: Icon(Icons.add_to_home_screen, size: 16, color: glowColor),
      label: Text('Tạo icon xử lý nhanh', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: context.palette.textMain)),
      backgroundColor: context.palette.surface,
      side: BorderSide(color: glowColor.withValues(alpha: 0.4), width: 1),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      onPressed: () => _createShortcut(type, label, iconRes),
    );
  }

  @override
  Widget build(BuildContext context) {
    // Trạng thái bật/tắt: ưu tiên trạng thái THẬT nếu đã lấy được.
    bool isActive = _status != null
        ? '${_status!['status']}'.toUpperCase() == 'ON'
        : (widget.device['is_active'] == true);

    Color glowColor = context.palette.primary;
    IconData icon = Icons.device_hub;

    if (_isAirPurifier) { glowColor = context.palette.cyan; icon = Icons.air; }
    if (_isFeeder) { glowColor = context.palette.purple; icon = Icons.pets; }
    if (_isCurtain) { glowColor = context.palette.success; icon = Icons.blinds; }
    if (_isSwitch) { glowColor = context.palette.cyan; icon = Icons.water_drop; }

    // ----- Trạng thái cửa (để đổi icon/nhãn + tô sáng nút đang hoạt động) -----
    final String doorState = '${_status?['door_state'] ?? 'unknown'}'.toLowerCase();
    String? statusLabel;
    if (_isCurtain && _status != null) {
      icon = (doorState == 'closed' || doorState == 'closing') ? Icons.blinds_closed : Icons.blinds;
      statusLabel = {
        'open': 'Đang mở',
        'opening': 'Đang mở...',
        'closed': 'Đã đóng',
        'closing': 'Đang đóng...',
        'stopped': 'Đã dừng',
        'partial': 'Mở một phần',
      }[doorState];
    }
    // Nút cửa đang hoạt động (để tô sáng): ưu tiên lệnh vừa bấm (lạc quan),
    // nếu chưa có thì suy từ trạng thái thật. KHÔNG khóa nút nào -> luôn bấm được
    // (backend đã tự chèn 'stop' trước khi đảo chiều nên an toàn).
    final String? activeDoorMode = (_pendingMode != null && const ['open', 'close', 'stop'].contains(_pendingMode))
        ? _pendingMode
        : const {
            'open': 'open',
            'opening': 'open',
            'closed': 'close',
            'closing': 'close',
            'stopped': 'stop',
          }[doorState];

    // ----- Máy lọc: xác định chip mode đang chạy để highlight + nhãn trạng thái -----
    final int purifierIndex = _isAirPurifier ? PurifierCycle.indexFromStatus(_status) : 0;
    // Ưu tiên mode vừa bấm (lạc quan) để tô sáng ngay, rồi mới reconcile theo trạng thái thật.
    final String purifierKey = _pendingMode != null
        ? (const {'1': 'low', '2': 'med', '3': 'high', 'auto': 'auto', 'sleep': 'sleep'}[_pendingMode]
            ?? PurifierCycle.steps[purifierIndex].key)
        : PurifierCycle.steps[purifierIndex].key;
    if (_isAirPurifier && _status != null) {
      final bool purifierOn = '${_status!['status']}'.toUpperCase() == 'ON';
      statusLabel = purifierOn ? 'Đang chạy: ${PurifierCycle.steps[purifierIndex].label}' : 'Đã tắt';
    }

    // ----- Máy cho ăn: online/offline + đang nhả hạt (máy không báo mức hạt/pin) -----
    if (_isFeeder && _status != null) {
      final bool feederOnline = '${_status!['status']}'.toUpperCase() == 'ON';
      final lastFeed = _status!['last_feed'];
      statusLabel = !feederOnline
          ? 'Mất kết nối'
          : _status!['feed_state'] == 'feeding'
              ? 'Đang nhả hạt...'
              : (lastFeed is int && lastFeed > 0 ? 'Sẵn sàng • lần trước $lastFeed phần' : 'Sẵn sàng');
    }

    if (_isSwitch && _status != null) {
      statusLabel = const {'ON': 'Đang chạy', 'OFF': 'Đã tắt'}['${_status!['status']}'.toUpperCase()]
          ?? 'Mất kết nối';
    }

    bool showSwitch = !_isFeeder && !_isCurtain;

    return AnimatedContainer(
      duration: const Duration(milliseconds: 300),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: context.palette.card,
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: isActive ? glowColor.withValues(alpha: 0.5) : context.palette.outline, width: 1.5),
        boxShadow: isActive ? [BoxShadow(color: glowColor.withValues(alpha: 0.15), blurRadius: 20, spreadRadius: 2)] : [],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(color: isActive ? glowColor.withValues(alpha: 0.2) : context.palette.surface, shape: BoxShape.circle),
                child: Icon(icon, color: isActive ? glowColor : context.palette.textSub, size: 24),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(_name, style: TextStyle(color: context.palette.textMain, fontWeight: FontWeight.bold, fontSize: 16)),
                    Text(
                      statusLabel ?? widget.device['brand'].toString().toUpperCase(),
                      style: TextStyle(color: statusLabel != null ? glowColor : context.palette.textSub, fontSize: 12),
                    ),
                  ],
                ),
              ),
              if (showSwitch)
                Switch.adaptive(
                  value: isActive,
                  activeTrackColor: glowColor,
                  onChanged: (widget.isOffline || _sending)
                      ? null
                      : (v) {
                          setState(() => _sending = true);
                          widget.onToggle(v);
                          // Reconcile trạng thái thật + mở khóa switch sau khi cloud kịp cập nhật.
                          _refreshAfterCommand().whenComplete(() {
                            if (mounted) setState(() => _sending = false);
                          });
                        },
                ),
              if (widget.dragHandle != null) ...[
                const SizedBox(width: 4),
                widget.dragHandle!,
              ],
            ],
          ),
          const SizedBox(height: 16),
          if (_isAirPurifier)
            Wrap(spacing: 8.0, runSpacing: 8.0, children: [
              _buildModeButton('Thấp', '1', glowColor, selected: purifierKey == 'low'),
              _buildModeButton('TB', '2', glowColor, selected: purifierKey == 'med'),
              _buildModeButton('Cao', '3', glowColor, selected: purifierKey == 'high'),
              _buildModeButton('Auto', 'auto', glowColor, selected: purifierKey == 'auto'),
              _buildModeButton('Sleep', 'sleep', glowColor, selected: purifierKey == 'sleep'),
            ]),
          if (_isFeeder)
            Wrap(spacing: 8.0, runSpacing: 8.0, children: [
              _buildModeButton('Nhả 1 phần', '1', glowColor),
              _buildModeButton('Nhả 2 phần', '2', glowColor),
              _buildModeButton('Nhả 3 phần', '3', glowColor),
            ]),
          if (_isCurtain)
            Wrap(spacing: 8.0, runSpacing: 8.0, children: [
              _buildModeButton('Mở cửa', 'open', glowColor, selected: activeDoorMode == 'open'),
              _buildModeButton('Dừng', 'stop', Colors.redAccent, selected: activeDoorMode == 'stop'),
              _buildModeButton('Đóng cửa', 'close', glowColor, selected: activeDoorMode == 'close'),
            ]),

          // NÚT TẠO ICON XỬ LÝ NHANH (shortcut ra home screen)
          if (_isAirPurifier || _isFeeder || _isCurtain) ...[
            const SizedBox(height: 12),
            if (_isAirPurifier)
              _buildShortcutButton(ShortcutType.purifierCycle, _name, ShortcutIcons.purifier(purifierKey), glowColor),
            if (_isFeeder)
              _buildShortcutButton(ShortcutType.feederFeed, _name, ShortcutIcons.feeder(), glowColor),
            if (_isCurtain)
              _buildShortcutButton(ShortcutType.doorToggle, _name, ShortcutIcons.door(doorState), glowColor),
          ],
        ],
      ),
    );
  }
}
