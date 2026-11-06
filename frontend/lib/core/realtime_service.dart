import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'auth_service.dart';
import 'config.dart';

/// Kênh trạng thái thời gian thực `/ws` (backend `services/realtime.py`).
///
/// MỘT kết nối cho cả app (huy hiệu "Live" ở tab Trợ lý cũng đọc từ đây —
/// `websocket_provider.dart` chỉ là lớp mỏng). `MainScreen` gọi [start] khi
/// vào app / quay lại foreground và [stop] khi app vào nền hoặc đăng xuất.
///
/// Giao thức: gửi `{"event":"connection.auth","token":...}` ngay sau khi nối
/// (token KHÔNG nằm trong URL — máy chủ ghi log URL), chờ `connection.ready`
/// mới coi là "live". Máy chủ ping mỗi ~25s, app trả `connection.pong`; im lặng
/// quá [silenceTimeout] ⇒ coi như chết, nối lại. Mất kết nối ⇒ thử lại theo
/// exponential backoff có jitter. Trong lúc không live, các màn hình tự quay về
/// poll HTTP như cũ (xem `SmartDeviceCard`, `FloorPlanTab`).
enum RealtimeStatus {
  /// Chưa bắt đầu / đã dừng (app ở nền, đăng xuất).
  idle,

  /// Đang nối / đang chờ máy chủ xác nhận token.
  connecting,

  /// Đã xác thực, đang nhận sự kiện.
  live,

  /// Vừa mất kết nối, đang chờ để thử lại.
  retrying,
}

/// Sự kiện của MỘT thiết bị. Payload máy chủ:
/// `{"event", "device_id", "timestamp", "data"}`.
class DeviceEvent {
  static const statusChanged = 'device.status_changed';
  static const commandCompleted = 'device.command_completed';
  static const offline = 'device.offline';
  static const online = 'device.online';

  final String event;
  final String deviceId;

  /// Giờ máy chủ (ms) lúc PHÁT sự kiện.
  final int timestamp;
  final Map<String, dynamic> data;

  const DeviceEvent({
    required this.event,
    required this.deviceId,
    required this.timestamp,
    required this.data,
  });

  /// Trạng thái thiết bị — cùng dạng `data` của `GET .../status`. Chỉ
  /// `device.status_changed` có; sự kiện khác (hoặc payload thiếu) trả null.
  Map<String, dynamic>? get state {
    final s = data['state'];
    return s is Map ? Map<String, dynamic>.from(s) : null;
  }

  /// Giờ máy chủ lúc BẮT ĐẦU đọc trạng thái này — so với `read_at_ms` của
  /// `GET .../status` để bản cũ về muộn không ghi đè bản mới.
  int? get readAtMs {
    final v = data['read_at_ms'];
    return v is num ? v.toInt() : null;
  }

  /// null nếu payload sai định dạng (không bao giờ ném).
  static DeviceEvent? tryParse(Map<String, dynamic> m) {
    final event = m['event'];
    final id = m['device_id'];
    if (event is! String || !event.startsWith('device.') || id is! String || id.isEmpty) {
      return null;
    }
    final ts = m['timestamp'];
    final data = m['data'];
    return DeviceEvent(
      event: event,
      deviceId: id,
      timestamp: ts is num ? ts.toInt() : 0,
      data: data is Map ? Map<String, dynamic>.from(data) : const {},
    );
  }
}

/// Giải mã 1 frame thành JSON object; null nếu không phải (không bao giờ ném).
Map<String, dynamic>? decodeRealtimeFrame(dynamic raw) {
  try {
    final text = raw is String ? raw : utf8.decode(raw as List<int>);
    final v = jsonDecode(text);
    return v is Map ? Map<String, dynamic>.from(v) : null;
  } catch (_) {
    return null;
  }
}

/// Trạng thái đọc lúc [incoming] có được ghi đè bản đang hiện (đọc lúc
/// [current]) không. Thiếu mốc (backend cũ) ⇒ nhận, như trước khi có /ws.
bool isFresherStatus(int? incoming, int? current) =>
    incoming == null || current == null || incoming >= current;

/// Kết nối thô — tách ra để test thay bằng bản giả.
abstract class RealtimeTransport {
  Future<void> get ready;
  Stream<dynamic> get stream;
  int? get closeCode;
  void send(String text);
  Future<void> close();
}

class _ChannelTransport implements RealtimeTransport {
  _ChannelTransport(Uri uri) : _ch = WebSocketChannel.connect(uri);
  final WebSocketChannel _ch;

  @override
  Future<void> get ready => _ch.ready;
  @override
  Stream<dynamic> get stream => _ch.stream;
  @override
  int? get closeCode => _ch.closeCode;
  @override
  void send(String text) => _ch.sink.add(text);
  @override
  Future<void> close() async {
    try {
      await _ch.sink.close(1000);
    } catch (_) {}
  }
}

typedef RealtimeTransportFactory = RealtimeTransport Function(Uri uri);
typedef RealtimeTokenProvider = Future<String?> Function();

class RealtimeService {
  /// Mã đóng của máy chủ: token sai / chưa được duyệt hoặc bị chặn / quá
  /// nhiều kết nối. Thử lại dồn dập không giải quyết được ⇒ chờ lâu.
  static const closeUnauthorized = 4401;
  static const closeForbidden = 4403;
  static const closeTooMany = 4429;

  RealtimeService({
    RealtimeTransportFactory? connect,
    RealtimeTokenProvider? token,
    Uri? uri,
    this.baseDelay = const Duration(seconds: 1),
    this.maxDelay = const Duration(seconds: 60),
    this.rejectedDelay = const Duration(minutes: 5),
    this.handshakeTimeout = const Duration(seconds: 10),
    this.silenceTimeout = const Duration(seconds: 70),
    math.Random? random,
  })  : _connect = connect ?? ((u) => _ChannelTransport(u)),
        _token = token ?? _defaultToken,
        _uri = uri ?? Uri.parse(AppConfig.wsUrl),
        _random = random ?? math.Random();

  static final RealtimeService instance = RealtimeService();

  final RealtimeTransportFactory _connect;
  final RealtimeTokenProvider _token;
  final Uri _uri;
  final math.Random _random;
  final Duration baseDelay;
  final Duration maxDelay;
  final Duration rejectedDelay;
  final Duration handshakeTimeout;
  final Duration silenceTimeout;

  final ValueNotifier<RealtimeStatus> status = ValueNotifier(RealtimeStatus.idle);
  final StreamController<DeviceEvent> _events = StreamController<DeviceEvent>.broadcast();

  bool get isLive => status.value == RealtimeStatus.live;

  /// Mọi sự kiện thiết bị (đã lọc quyền ở máy chủ).
  Stream<DeviceEvent> get events => _events.stream;

  /// Sự kiện của riêng 1 thiết bị — mỗi thẻ chỉ nghe thiết bị của nó, nên một
  /// sự kiện chỉ rebuild đúng thẻ đó chứ không rebuild cả Dashboard.
  Stream<DeviceEvent> eventsFor(String deviceId) => _events.stream.where((e) => e.deviceId == deviceId);

  bool _wanted = false;
  bool _connecting = false;

  /// Mỗi lần nối +1; callback của kết nối cũ so `gen` và tự bỏ qua ⇒ không
  /// bao giờ có 2 kết nối cùng sống, kể cả khi start/stop dồn dập.
  int _gen = 0;
  int _attempt = 0;
  RealtimeTransport? _transport;
  StreamSubscription<dynamic>? _sub;
  Timer? _retryTimer;
  Timer? _handshakeTimer;
  Timer? _watchdog;
  DateTime _lastRx = DateTime.now();

  static Future<String?> _defaultToken() async {
    try {
      return await AuthService.accessToken();
    } catch (_) {
      return null; // backend xác thực TẮT vẫn nhận token rỗng
    }
  }

  /// Bắt đầu (hoặc giữ) kết nối. Gọi nhiều lần không tạo kết nối trùng.
  /// Đang chờ backoff thì nối NGAY (vd. app vừa quay lại foreground).
  void start() {
    _wanted = true;
    if (_transport != null || _connecting) return;
    _retryTimer?.cancel();
    _retryTimer = null;
    _open();
  }

  /// Người dùng bấm "Mất kết nối": bỏ backoff, nối lại ngay.
  void reconnectNow() {
    _attempt = 0;
    start();
  }

  /// Đóng hẳn (app vào nền / đăng xuất). Không tự nối lại tới lần [start] sau.
  void stop() {
    _wanted = false;
    _retryTimer?.cancel();
    _retryTimer = null;
    _teardown();
    _attempt = 0;
    status.value = RealtimeStatus.idle;
  }

  /// Độ trễ trước lần thử lại thứ [attempt] (0-based): 1s, 2s, 4s... tối đa
  /// [maxDelay], jitter ±20% để cả nhà không cùng nối lại một lúc sau khi máy
  /// chủ khởi động lại. Bị từ chối (4401/4403/4429) ⇒ [rejectedDelay].
  Duration backoffFor(int attempt, [int? closeCode]) {
    if (closeCode == closeUnauthorized || closeCode == closeForbidden || closeCode == closeTooMany) {
      return rejectedDelay;
    }
    final exp = baseDelay.inMilliseconds * math.pow(2, math.min(attempt, 16));
    final capped = math.min(exp.toDouble(), maxDelay.inMilliseconds.toDouble());
    final jitter = 0.8 + 0.4 * _random.nextDouble();
    return Duration(milliseconds: (capped * jitter).round());
  }

  Future<void> _open() async {
    final gen = ++_gen;
    _connecting = true;
    status.value = RealtimeStatus.connecting;
    RealtimeTransport? t;
    try {
      final token = await _token();
      if (gen != _gen) return;
      t = _connect(_uri);
      _transport = t;
      await t.ready.timeout(handshakeTimeout);
      if (gen != _gen) return;
      _lastRx = DateTime.now();
      final transport = t;
      _sub = transport.stream.listen(
        (raw) => _onFrame(gen, raw),
        onError: (Object _) => _fail(gen, transport.closeCode),
        onDone: () => _fail(gen, transport.closeCode),
        cancelOnError: true,
      );
      transport.send(jsonEncode({'event': 'connection.auth', 'token': token ?? ''}));
      // Không nhận `connection.ready` trong hạn ⇒ máy chủ treo / proxy nuốt.
      _handshakeTimer = Timer(handshakeTimeout, () => _fail(gen));
    } catch (e) {
      debugPrint('Realtime: không nối được ($e)');
      _fail(gen, t?.closeCode);
    } finally {
      if (gen == _gen) _connecting = false;
    }
  }

  void _onFrame(int gen, dynamic raw) {
    if (gen != _gen) return;
    _lastRx = DateTime.now();
    final m = decodeRealtimeFrame(raw);
    if (m == null) return; // payload rác: bỏ qua, KHÔNG đóng kết nối
    switch (m['event']) {
      case 'connection.ready':
        _handshakeTimer?.cancel();
        _attempt = 0;
        _startWatchdog(gen);
        status.value = RealtimeStatus.live;
      case 'connection.ping':
        _send({'event': 'connection.pong'});
      case 'connection.pong':
        break;
      default:
        final e = DeviceEvent.tryParse(m);
        if (e != null) _events.add(e);
    }
  }

  void _send(Map<String, dynamic> msg) {
    try {
      _transport?.send(jsonEncode(msg));
    } catch (_) {
      // Socket vừa đóng: onDone sẽ lo việc nối lại.
    }
  }

  void _startWatchdog(int gen) {
    _watchdog?.cancel();
    final every = Duration(milliseconds: math.max(silenceTimeout.inMilliseconds ~/ 4, 50));
    _watchdog = Timer.periodic(every, (_) {
      if (DateTime.now().difference(_lastRx) > silenceTimeout) {
        debugPrint('Realtime: im lặng quá ${silenceTimeout.inSeconds}s — nối lại.');
        _fail(gen);
      }
    });
  }

  /// Gỡ kết nối hiện tại và vô hiệu hóa mọi callback của nó.
  void _teardown() {
    _gen++;
    _connecting = false;
    _handshakeTimer?.cancel();
    _handshakeTimer = null;
    _watchdog?.cancel();
    _watchdog = null;
    final sub = _sub;
    _sub = null;
    if (sub != null) unawaited(sub.cancel());
    final t = _transport;
    _transport = null;
    if (t != null) unawaited(t.close());
  }

  void _fail(int gen, [int? closeCode]) {
    if (gen != _gen) return;
    _teardown();
    if (!_wanted) {
      status.value = RealtimeStatus.idle;
      return;
    }
    status.value = RealtimeStatus.retrying;
    final delay = backoffFor(_attempt++, closeCode);
    _retryTimer?.cancel();
    _retryTimer = Timer(delay, () {
      _retryTimer = null;
      if (_wanted && _transport == null && !_connecting) _open();
    });
  }
}
