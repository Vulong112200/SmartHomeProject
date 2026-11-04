import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../core/auth_service.dart';
import '../theme/app_colors.dart';

/// Đăng nhập / đăng ký bằng email + mật khẩu (Supabase Auth).
///
/// Giữ cả luồng ĐĂNG KÝ: nó ăn khớp với cơ chế chờ-duyệt ở backend (người lạ
/// vào là `guest`/`pending`, chủ nhà duyệt sau). Bỏ đăng ký thì chủ nhà phải
/// tự tạo tài khoản và đặt lại mật khẩu cho từng người trong dashboard Supabase.
class LoginScreen extends StatefulWidget {
  /// Gọi khi đăng nhập/đăng ký xong để AuthGate tải lại hồ sơ.
  final VoidCallback onSignedIn;

  const LoginScreen({super.key, required this.onSignedIn});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _emailCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  final _nameCtrl = TextEditingController();

  bool _isSignUp = false;
  bool _busy = false;
  bool _obscure = true;
  String? _error;
  String? _info;

  @override
  void dispose() {
    _emailCtrl.dispose();
    _passCtrl.dispose();
    _nameCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _busy = true;
      _error = null;
      _info = null;
    });
    try {
      if (_isSignUp) {
        await AuthService.signUp(
          _emailCtrl.text,
          _passCtrl.text,
          displayName: _nameCtrl.text.trim().isEmpty ? null : _nameCtrl.text.trim(),
        );
        if (!AuthService.isLoggedIn) {
          // Project bật "Confirm email": tài khoản đã tạo nhưng chưa có phiên.
          setState(() {
            _info = 'Đã tạo tài khoản. Kiểm tra email để xác nhận rồi đăng nhập.';
            _isSignUp = false;
          });
          return;
        }
      } else {
        await AuthService.signIn(_emailCtrl.text, _passCtrl.text);
      }
      if (mounted) widget.onSignedIn();
    } on AuthException catch (e) {
      setState(() => _error = _friendly(e.message));
    } catch (e) {
      setState(() => _error = 'Không kết nối được máy chủ đăng nhập. Thử lại sau.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Supabase trả lỗi tiếng Anh; dịch những cái hay gặp sang tiếng Việt.
  String _friendly(String raw) {
    final m = raw.toLowerCase();
    if (m.contains('invalid login credentials')) {
      return 'Email hoặc mật khẩu không đúng.';
    }
    if (m.contains('email not confirmed')) {
      return 'Email chưa được xác nhận. Kiểm tra hộp thư của bạn.';
    }
    if (m.contains('user already registered')) {
      return 'Email này đã có tài khoản. Hãy đăng nhập.';
    }
    if (m.contains('password should be at least')) {
      return 'Mật khẩu quá ngắn (tối thiểu 6 ký tự).';
    }
    return raw;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: context.palette.background,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Form(
                key: _formKey,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Icon(Icons.home_rounded, size: 64, color: context.palette.primary),
                    const SizedBox(height: 16),
                    Text(
                      'Nhà thông minh',
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.headlineSmall,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      _isSignUp
                          ? 'Tạo tài khoản, chủ nhà sẽ duyệt sau'
                          : 'Đăng nhập để điều khiển thiết bị',
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                    const SizedBox(height: 28),

                    if (_isSignUp) ...[
                      TextFormField(
                        controller: _nameCtrl,
                        textInputAction: TextInputAction.next,
                        decoration: const InputDecoration(
                          labelText: 'Tên hiển thị (tùy chọn)',
                          prefixIcon: Icon(Icons.badge_outlined),
                        ),
                      ),
                      const SizedBox(height: 12),
                    ],

                    TextFormField(
                      controller: _emailCtrl,
                      keyboardType: TextInputType.emailAddress,
                      textInputAction: TextInputAction.next,
                      autofillHints: const [AutofillHints.email],
                      decoration: const InputDecoration(
                        labelText: 'Email',
                        prefixIcon: Icon(Icons.mail_outline),
                      ),
                      validator: (v) {
                        final t = (v ?? '').trim();
                        if (t.isEmpty) return 'Nhập email';
                        if (!t.contains('@') || !t.contains('.')) return 'Email không hợp lệ';
                        return null;
                      },
                    ),
                    const SizedBox(height: 12),

                    TextFormField(
                      controller: _passCtrl,
                      obscureText: _obscure,
                      textInputAction: TextInputAction.done,
                      autofillHints: const [AutofillHints.password],
                      onFieldSubmitted: (_) => _busy ? null : _submit(),
                      decoration: InputDecoration(
                        labelText: 'Mật khẩu',
                        prefixIcon: const Icon(Icons.lock_outline),
                        suffixIcon: IconButton(
                          icon: Icon(_obscure ? Icons.visibility_off : Icons.visibility),
                          onPressed: () => setState(() => _obscure = !_obscure),
                        ),
                      ),
                      validator: (v) {
                        if ((v ?? '').isEmpty) return 'Nhập mật khẩu';
                        if (_isSignUp && (v ?? '').length < 6) {
                          return 'Mật khẩu tối thiểu 6 ký tự';
                        }
                        return null;
                      },
                    ),

                    if (_error != null) ...[
                      const SizedBox(height: 16),
                      _Banner(text: _error!, isError: true),
                    ],
                    if (_info != null) ...[
                      const SizedBox(height: 16),
                      _Banner(text: _info!, isError: false),
                    ],

                    const SizedBox(height: 24),
                    FilledButton(
                      onPressed: _busy ? null : _submit,
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        child: _busy
                            ? const SizedBox(
                                height: 20,
                                width: 20,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            : Text(_isSignUp ? 'Tạo tài khoản' : 'Đăng nhập'),
                      ),
                    ),
                    const SizedBox(height: 8),
                    TextButton(
                      onPressed: _busy
                          ? null
                          : () => setState(() {
                                _isSignUp = !_isSignUp;
                                _error = null;
                                _info = null;
                              }),
                      child: Text(_isSignUp
                          ? 'Đã có tài khoản? Đăng nhập'
                          : 'Chưa có tài khoản? Đăng ký'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Banner extends StatelessWidget {
  final String text;
  final bool isError;
  const _Banner({required this.text, required this.isError});

  @override
  Widget build(BuildContext context) {
    final color = isError ? Colors.redAccent : context.palette.primary;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        children: [
          Icon(isError ? Icons.error_outline : Icons.info_outline, color: color, size: 20),
          const SizedBox(width: 10),
          Expanded(child: Text(text, style: TextStyle(color: color))),
        ],
      ),
    );
  }
}
