import 'dart:async';

import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../core/auth_service.dart';
import '../core/config.dart';
import '../theme/app_colors.dart';
import 'login_screen.dart';
import 'pending_screen.dart';

/// Năm trạng thái, không phải hai.
///
/// `loading` tồn tại vì nếu không có nó, cold start sẽ **nháy màn đăng nhập**
/// trong lúc session đã lưu chưa kịp resolve — người dùng tưởng mình bị đăng
/// xuất. `offline` tồn tại vì rớt mạng KHÁC hết phiên: đăng xuất người ta chỉ
/// vì Render đang ngủ là bắt gõ lại mật khẩu vô cớ.
enum _GateState { loading, signedOut, pending, offline, ready }

/// Quyết định hiển thị màn nào: đăng nhập, chờ duyệt, mất mạng, hay app chính.
class AuthGate extends StatefulWidget {
  /// Dựng app chính khi đã sẵn sàng. Nhận hồ sơ để không phải fetch lại.
  final Widget Function(HouseholdProfile profile) builder;

  const AuthGate({super.key, required this.builder});

  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> {
  _GateState _state = _GateState.loading;
  HouseholdProfile? _profile;

  /// ⚠️ Phải cancel trong dispose — subscription không hủy sẽ gọi setState trên
  /// widget đã chết sau khi AuthGate bị thay thế.
  StreamSubscription<AuthState>? _authSub;

  @override
  void initState() {
    super.initState();

    if (AppConfig.authEnabled) {
      _authSub = AuthService.onAuthChange.listen((_) {
        if (mounted) _bootstrap();
      });
      // 401 từ bất kỳ API nào -> quay về màn đăng nhập.
      AuthService.onUnauthorized = () {
        if (mounted) setState(() => _state = _GateState.signedOut);
      };
    }

    _bootstrap();
  }

  @override
  void dispose() {
    _authSub?.cancel();
    AuthService.onUnauthorized = null;
    super.dispose();
  }

  Future<void> _bootstrap() async {
    // Chưa cấu hình Supabase: app chạy y như trước khi có đăng nhập, khớp với
    // backend đang để xác thực TẮT. Không có nhánh này thì một bản build thiếu
    // khóa sẽ kẹt ở màn login vĩnh viễn — không ai vào được nhà mình.
    if (!AppConfig.authEnabled) {
      if (mounted) {
        setState(() {
          _profile = HouseholdProfile.openHouse;
          _state = _GateState.ready;
        });
      }
      return;
    }

    if (mounted) setState(() => _state = _GateState.loading);

    if (!AuthService.isLoggedIn && await AuthService.readAppToken() == null) {
      if (mounted) setState(() => _state = _GateState.signedOut);
      return;
    }

    final me = await fetchMe();
    if (!mounted) return;

    switch (me.result) {
      case MeResult.ok:
        final profile = me.profile!;
        // Làm mới app-token mỗi lần vào app: Home Widget và shortcut đọc nó ở
        // isolate nền, nơi không có cách nào tự xin token.
        unawaited(AuthService.refreshAppToken());
        setState(() {
          _profile = profile;
          _state = profile.isActive ? _GateState.ready : _GateState.pending;
        });
      case MeResult.unauthorized:
        await AuthService.handleUnauthorized();
        if (mounted) setState(() => _state = _GateState.signedOut);
      case MeResult.offline:
      case MeResult.serverError:
        setState(() => _state = _GateState.offline);
    }
  }

  Future<void> _signOut() async {
    await AuthService.signOut();
    if (mounted) setState(() => _state = _GateState.signedOut);
  }

  @override
  Widget build(BuildContext context) {
    switch (_state) {
      case _GateState.loading:
        return const _LoadingScreen();
      case _GateState.signedOut:
        return LoginScreen(onSignedIn: _bootstrap);
      case _GateState.pending:
        return PendingScreen(
          profile: _profile!,
          onRetry: _bootstrap,
          onSignOut: _signOut,
        );
      case _GateState.offline:
        return OfflineScreen(onRetry: _bootstrap, onSignOut: _signOut);
      case _GateState.ready:
        return widget.builder(_profile!);
    }
  }
}

class _LoadingScreen extends StatelessWidget {
  const _LoadingScreen();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: context.palette.background,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.home_rounded, size: 56, color: context.palette.primary),
            const SizedBox(height: 20),
            const SizedBox(
              height: 24,
              width: 24,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
          ],
        ),
      ),
    );
  }
}
