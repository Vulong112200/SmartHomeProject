import 'dart:async'; // Bắt buộc để dùng Timer
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:http/http.dart' as http;
import '../theme/app_colors.dart';
import '../core/device_api.dart';
import '../core/shortcut_service.dart';
import '../core/shortcut_handler.dart';
import '../core/widget_service.dart';

class DashboardTab extends StatefulWidget {
  const DashboardTab({super.key});

  @override
  State<DashboardTab> createState() => _DashboardTabState();
}

class _DashboardTabState extends State<DashboardTab> {
  final String baseUrl = 'https://vuhp-smarthome.onrender.com';
  List<dynamic> devices = [];
  bool isLoading = true;
  bool isOffline = false; // Cờ theo dõi trạng thái mạng
  bool isWaking = false;  // Đang đánh thức server (Render free-tier ngủ -> cold start)
  Timer? _retryTimer;     // Bộ đếm giờ tự thử lại

  @override
  void initState() {
    super.initState();
    _bootstrap();
  }

  // Đánh thức server trước (Render free-tier ngủ sau ~15 phút, cold start 30-50s),
  // hiển thị trạng thái "đang đánh thức" thay vì treo im lặng, rồi mới tải thiết bị.
  Future<void> _bootstrap() async {
    setState(() => isWaking = true);
    try {
      await http.get(Uri.parse('$baseUrl/health')).timeout(const Duration(seconds: 35));
    } catch (_) {
      // Bỏ qua: nếu thất bại, fetchDevices bên dưới sẽ xử lý offline.
    }
    if (!mounted) return;
    setState(() => isWaking = false);
    fetchDevices();
  }

  @override
  void dispose() {
    _retryTimer?.cancel(); // Tắt timer khi thoát màn hình
    super.dispose();
  }

  // 1. HÀM LẤY DỮ LIỆU ĐƯỢC NÂNG CẤP (Có Timeout và Auto-Retry)
  Future<void> fetchDevices() async {
    try {
      // Ép thời gian chờ là 5 giây, nếu server đơ thì báo lỗi ngay
      final response = await http.get(Uri.parse('$baseUrl/api/devices'))
                                 .timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final data = json.decode(utf8.decode(response.bodyBytes));
        setState(() {
          devices = data['data'];
          isLoading = false;
          isOffline = false; // Đã có mạng
        });
        _retryTimer?.cancel(); // Tắt bộ thử lại
        WidgetService.refreshAll(); // Đồng bộ trạng thái lên Home Screen Widget
      } else {
        _handleOffline();
      }
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

  @override
  Widget build(BuildContext context) {
    int activeCount = devices.where((d) => d['is_active'] == true).length;

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
                    const CircularProgressIndicator(color: AppColors.primary),
                    if (isWaking) ...[
                      const SizedBox(height: 16),
                      const Text(
                        "Đang đánh thức máy chủ...",
                        style: TextStyle(color: AppColors.textSub, fontSize: 13),
                      ),
                    ],
                  ],
                ),
              )
            // 4. KÉO ĐỂ REFRESH (Pull to Refresh)
            : RefreshIndicator(
              onRefresh: fetchDevices,
              color: AppColors.primary,
              backgroundColor: AppColors.surface,
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
                              const Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text("Welcome Home,", style: TextStyle(color: AppColors.textSub, fontSize: 14)),
                                  Text("Vũ 🖖", style: TextStyle(color: AppColors.textMain, fontSize: 28, fontWeight: FontWeight.bold)),
                                ],
                              ),
                              Container(
                                padding: const EdgeInsets.all(12),
                                decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(16)),
                                child: const Icon(Icons.wb_sunny_rounded, color: Colors.orangeAccent),
                              ),
                            ],
                          ),
                          const SizedBox(height: 24),
                          Container(
                            padding: const EdgeInsets.all(20),
                            decoration: BoxDecoration(
                              gradient: AppColors.primaryGradient,
                              borderRadius: BorderRadius.circular(24),
                              boxShadow: [BoxShadow(color: AppColors.primary.withValues(alpha: 0.3), blurRadius: 20, offset: const Offset(0, 8))],
                            ),
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                _buildStat("Nhiệt độ", "24°C", Icons.thermostat),
                                _buildStat("Độ ẩm", "60%", Icons.water_drop),
                                _buildStat("Đang bật", "$activeCount thiết bị", Icons.bolt),
                              ],
                            ),
                          ).animate().fade(duration: 500.ms).slideY(begin: 0.2),
                        ],
                      ),
                    ),
                  ),

                  if (devices.isEmpty && !isLoading)
                    const SliverFillRemaining(
                      child: Center(child: Text("Không có dữ liệu thiết bị", style: TextStyle(color: AppColors.textSub))),
                    )
                  else
                    SliverList(
                      delegate: SliverChildBuilderDelegate(
                        (context, index) {
                          return Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 8),
                            child: SmartDeviceCard(
                              device: devices[index],
                              baseUrl: baseUrl,
                              isOffline: isOffline, // Truyền trạng thái mạng vào Card
                              onToggle: (val) => _toggleDeviceState(devices[index], val),
                            ).animate().fade(delay: (100 * index).ms).slideX(begin: 0.1),
                          );
                        },
                        childCount: devices.length,
                      ),
                    ),
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
  final Function(bool) onToggle;

  const SmartDeviceCard({super.key, required this.device, required this.baseUrl, required this.isOffline, required this.onToggle});

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

  bool get _isAirPurifier => _name.toLowerCase().contains('lọc');
  bool get _isFeeder => _name.toLowerCase().contains('mèo') || _name.toLowerCase().contains('ăn');
  bool get _isCurtain => _name.toLowerCase().contains('cửa');

  bool get _needsStatus => _isAirPurifier || _isCurtain;

  @override
  void initState() {
    super.initState();
    // Chỉ máy lọc & cửa mới cần lấy trạng thái thật để hiển thị đúng.
    if (_needsStatus) {
      _refreshStatus();
      // Tự động cập nhật định kỳ để trạng thái luôn tươi, không cần kéo reload.
      _pollTimer = Timer.periodic(const Duration(seconds: 6), (_) => _refreshStatus());
    }
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
        _snack('Đã chọn: $label', AppColors.primary);
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
          color: selected ? Colors.white : (enabled ? AppColors.textMain : AppColors.textSub),
        ),
      ),
      backgroundColor: selected ? glowColor : AppColors.surface,
      side: BorderSide(color: glowColor.withValues(alpha: selected ? 0.9 : 0.3), width: 1),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      onPressed: enabled ? () => _sendMode(label, modeValue) : null,
    );
  }

  Widget _buildShortcutButton(String type, String label, String iconRes, Color glowColor) {
    return ActionChip(
      avatar: Icon(Icons.add_to_home_screen, size: 16, color: glowColor),
      label: const Text('Tạo icon xử lý nhanh', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: AppColors.textMain)),
      backgroundColor: AppColors.surface,
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

    Color glowColor = AppColors.primary;
    IconData icon = Icons.device_hub;

    if (_isAirPurifier) { glowColor = AppColors.cyan; icon = Icons.air; }
    if (_isFeeder) { glowColor = AppColors.purple; icon = Icons.pets; }
    if (_isCurtain) { glowColor = AppColors.success; icon = Icons.blinds; }

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

    bool showSwitch = !_isFeeder && !_isCurtain;

    return AnimatedContainer(
      duration: const Duration(milliseconds: 300),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: isActive ? glowColor.withValues(alpha: 0.5) : Colors.white10, width: 1.5),
        boxShadow: isActive ? [BoxShadow(color: glowColor.withValues(alpha: 0.15), blurRadius: 20, spreadRadius: 2)] : [],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(color: isActive ? glowColor.withValues(alpha: 0.2) : AppColors.surface, shape: BoxShape.circle),
                child: Icon(icon, color: isActive ? glowColor : AppColors.textSub, size: 24),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(_name, style: const TextStyle(color: AppColors.textMain, fontWeight: FontWeight.bold, fontSize: 16)),
                    Text(
                      statusLabel ?? widget.device['brand'].toString().toUpperCase(),
                      style: TextStyle(color: statusLabel != null ? glowColor : AppColors.textSub, fontSize: 12),
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
