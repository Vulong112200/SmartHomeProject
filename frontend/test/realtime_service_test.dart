import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/core/realtime_service.dart';

/// Socket giả: test đóng vai máy chủ.
class FakeTransport implements RealtimeTransport {
  FakeTransport({this.failReady = false});

  final bool failReady;
  final StreamController<dynamic> _in = StreamController<dynamic>();
  final List<Map<String, dynamic>> sent = [];
  bool closed = false;
  int? code;

  @override
  Future<void> get ready => failReady ? Future.error(Exception('mất mạng')) : Future.value();
  @override
  Stream<dynamic> get stream => _in.stream;
  @override
  int? get closeCode => code;
  @override
  void send(String text) {
    if (closed) throw StateError('đã đóng');
    sent.add(jsonDecode(text) as Map<String, dynamic>);
  }

  @override
  Future<void> close() async {
    closed = true;
    if (!_in.isClosed) await _in.close();
  }

  void serverSend(Object msg) => _in.add(msg is String ? msg : jsonEncode(msg));
  void serverClose([int? closeCode]) {
    code = closeCode;
    if (!_in.isClosed) _in.close();
  }

  void sendReady() => serverSend({'event': 'connection.ready', 'device_id': null, 'timestamp': 1, 'data': {}});
}

class Harness {
  Harness({
    Duration silence = const Duration(seconds: 30),
    Duration handshake = const Duration(seconds: 5),
    bool Function(int n)? failReadyOn,
  }) {
    rt = RealtimeService(
      connect: (uri) {
        final t = FakeTransport(failReady: failReadyOn?.call(transports.length) ?? false);
        transports.add(t);
        return t;
      },
      token: () async => 'tok-123',
      uri: Uri.parse('ws://test/ws'),
      baseDelay: const Duration(milliseconds: 20),
      maxDelay: const Duration(milliseconds: 80),
      rejectedDelay: const Duration(hours: 1),
      handshakeTimeout: handshake,
      silenceTimeout: silence,
      random: math.Random(1),
    );
  }

  late final RealtimeService rt;
  final List<FakeTransport> transports = [];
  FakeTransport get last => transports.last;
  int get open => transports.where((t) => !t.closed).length;
}

Future<void> pump([int ms = 5]) => Future<void>.delayed(Duration(milliseconds: ms));

Map<String, dynamic> statusEvent(String id, String status, int readAt) => {
      'event': 'device.status_changed',
      'device_id': id,
      'timestamp': readAt + 1,
      'data': {'brand': 'tuya', 'state': {'device_id': id, 'status': status}, 'read_at_ms': readAt},
    };

void main() {
  group('DeviceEvent / tiện ích', () {
    test('parse đúng payload status_changed', () {
      final e = DeviceEvent.tryParse(statusEvent('lamp', 'ON', 100))!;
      expect(e.event, DeviceEvent.statusChanged);
      expect(e.deviceId, 'lamp');
      expect(e.state!['status'], 'ON');
      expect(e.readAtMs, 100);
    });

    test('payload sai định dạng -> null, không ném', () {
      expect(DeviceEvent.tryParse({'event': 'device.status_changed'}), isNull); // thiếu id
      expect(DeviceEvent.tryParse({'event': 'connection.ping', 'device_id': 'x'}), isNull);
      expect(DeviceEvent.tryParse({'event': 42, 'device_id': 'x'}), isNull);
      final e = DeviceEvent.tryParse({'event': 'device.offline', 'device_id': 'x', 'data': 'rác'})!;
      expect(e.state, isNull);
      expect(e.readAtMs, isNull);
      expect(decodeRealtimeFrame('{không phải json'), isNull);
      expect(decodeRealtimeFrame('[1,2]'), isNull);
      expect(decodeRealtimeFrame(utf8.encode('{"a":1}')), {'a': 1});
    });

    test('bản đọc cũ về muộn không ghi đè bản mới', () {
      expect(isFresherStatus(200, 100), isTrue);
      expect(isFresherStatus(100, 100), isTrue);
      expect(isFresherStatus(99, 100), isFalse);
      expect(isFresherStatus(null, 100), isTrue); // backend cũ, không có mốc
      expect(isFresherStatus(50, null), isTrue);
    });

    test('backoff tăng dần, có trần, jitter ±20%, bị từ chối thì chờ lâu', () {
      final rt = RealtimeService(
        connect: (_) => FakeTransport(),
        baseDelay: const Duration(seconds: 1),
        maxDelay: const Duration(seconds: 60),
        rejectedDelay: const Duration(minutes: 5),
        random: math.Random(7),
      );
      for (final (attempt, nominal) in [(0, 1000), (1, 2000), (3, 8000), (10, 60000), (50, 60000)]) {
        final ms = rt.backoffFor(attempt).inMilliseconds;
        expect(ms, inInclusiveRange(nominal * 0.8, nominal * 1.2), reason: 'lần $attempt');
      }
      for (final code in [4401, 4403, 4429]) {
        expect(rt.backoffFor(0, code), const Duration(minutes: 5));
      }
    });
  });

  group('RealtimeService', () {
    test('gửi token ở frame đầu, live khi có ready, trả pong, phát sự kiện, bỏ payload rác', () async {
      final h = Harness();
      final events = <DeviceEvent>[];
      final sub = h.rt.eventsFor('lamp').listen(events.add);
      h.rt.start();
      await pump();
      expect(h.rt.status.value, RealtimeStatus.connecting);
      expect(h.last.sent.single, {'event': 'connection.auth', 'token': 'tok-123'});

      h.last.sendReady();
      await pump();
      expect(h.rt.isLive, isTrue);

      h.last.serverSend({'event': 'connection.ping', 'device_id': null, 'timestamp': 1, 'data': {}});
      h.last.serverSend('{rác');
      h.last.serverSend([1, 2, 3]);
      h.last.serverSend(statusEvent('other', 'ON', 1));
      h.last.serverSend(statusEvent('lamp', 'ON', 2));
      await pump();
      expect(h.last.sent.last, {'event': 'connection.pong'});
      expect(events.map((e) => e.state!['status']), ['ON']);
      expect(h.rt.isLive, isTrue, reason: 'payload rác không làm đóng kết nối');

      await sub.cancel();
      h.rt.stop();
    });

    test('start() lặp lại không tạo kết nối trùng', () async {
      final h = Harness();
      h.rt.start();
      h.rt.start();
      h.rt.reconnectNow();
      await pump();
      h.rt.start();
      expect(h.transports.length, 1);
      h.rt.stop();
    });

    test('máy chủ đóng -> tự nối lại (backoff) và chỉ 1 kết nối mở', () async {
      final h = Harness();
      h.rt.start();
      await pump();
      h.last.sendReady();
      await pump();
      h.last.serverClose(1006);
      await pump();
      expect(h.rt.status.value, RealtimeStatus.retrying);
      await pump(60);
      expect(h.transports.length, 2);
      h.last.sendReady();
      await pump();
      expect(h.rt.isLive, isTrue);
      expect(h.open, 1);
      h.rt.stop();
    });

    test('mất mạng lúc nối -> thử lại tới khi được', () async {
      final h = Harness(failReadyOn: (n) => n < 2); // 2 lần đầu lỗi
      h.rt.start();
      await pump(300);
      expect(h.transports.length, 3);
      h.last.sendReady();
      await pump();
      expect(h.rt.isLive, isTrue);
      expect(h.open, 1);
      h.rt.stop();
    });

    test('bị từ chối 4403 -> KHÔNG nối lại dồn dập', () async {
      final h = Harness();
      h.rt.start();
      await pump();
      h.last.serverClose(RealtimeService.closeForbidden);
      await pump(200);
      expect(h.transports.length, 1);
      expect(h.rt.status.value, RealtimeStatus.retrying);
      // Người dùng bấm "Mất kết nối" -> thử ngay, không chờ.
      h.rt.reconnectNow();
      await pump();
      expect(h.transports.length, 2);
      h.rt.stop();
    });

    test('không nhận ready trong hạn -> bỏ và nối lại', () async {
      final h = Harness(handshake: const Duration(milliseconds: 50));
      h.rt.start();
      await pump(150);
      expect(h.transports.first.closed, isTrue);
      expect(h.transports.length, greaterThanOrEqualTo(2));
      h.rt.stop();
    });

    test('máy chủ im lặng quá hạn (kết nối chết) -> nối lại', () async {
      final h = Harness(silence: const Duration(milliseconds: 120));
      h.rt.start();
      await pump();
      h.last.sendReady();
      await pump();
      expect(h.rt.isLive, isTrue);
      await pump(300);
      expect(h.transports.first.closed, isTrue);
      expect(h.transports.length, greaterThanOrEqualTo(2));
      h.rt.stop();
    });

    test('stop() đóng kết nối, không nối lại, sự kiện cũ không lọt', () async {
      final h = Harness();
      final events = <DeviceEvent>[];
      h.rt.events.listen(events.add);
      h.rt.start();
      await pump();
      final first = h.last;
      first.sendReady();
      await pump();
      h.rt.stop();
      expect(h.rt.status.value, RealtimeStatus.idle);
      expect(first.closed, isTrue);
      await pump(100);
      expect(h.transports.length, 1);
      expect(events, isEmpty);
    });
  });
}
