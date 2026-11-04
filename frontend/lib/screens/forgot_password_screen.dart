import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../core/auth_service.dart';
import '../theme/app_colors.dart';
import 'password_field.dart';

/// Quên mật khẩu: nhập email -> nhận MÃ qua email -> nhập mã + mật khẩu mới.
/// Xong là đã đăng nhập: trả `true` qua Navigator.pop để màn trước vào app.
class ForgotPasswordScreen extends StatefulWidget {
  final String initialEmail;
  const ForgotPasswordScreen({super.key, this.initialEmail = ''});

  @override
  State<ForgotPasswordScreen> createState() => _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends State<ForgotPasswordScreen> {
  final _formKey = GlobalKey<FormState>();
  late final _email = TextEditingController(text: widget.initialEmail);
  final _code = TextEditingController();
  final _pass = TextEditingController();
  final _pass2 = TextEditingController();
  bool _codeSent = false;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    for (final c in [_email, _code, _pass, _pass2]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _guard(Future<void> Function() action, {bool validate = true}) async {
    if (validate && !(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
    } on AuthException catch (e) {
      if (mounted) setState(() => _error = friendlyAuthError(e.message));
    } catch (_) {
      if (mounted) setState(() => _error = 'Không kết nối được máy chủ đăng nhập. Thử lại sau.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // Gửi lại mã: email đã khóa (đã hợp lệ), không bắt kiểm các ô mã/mật khẩu đang trống.
  Future<void> _sendCode() => _guard(() async {
        await AuthService.sendPasswordResetCode(_email.text);
        if (mounted) setState(() => _codeSent = true);
      }, validate: !_codeSent);

  Future<void> _reset() => _guard(() async {
        await AuthService.resetPasswordWithCode(_email.text, _code.text, _pass.text);
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Đã đặt mật khẩu mới.')));
        Navigator.pop(context, true);
      });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Scaffold(
      appBar: AppBar(title: const Text('Quên mật khẩu')),
      body: SafeArea(
        child: Form(
          key: _formKey,
          child: ListView(
            padding: const EdgeInsets.all(24),
            children: [
              Text(
                _codeSent
                    ? 'Đã gửi mã tới ${_email.text.trim()}. Mở email, nhập mã và mật khẩu mới. '
                        'Không thấy thì xem cả mục Thư rác/Spam.'
                    : 'Nhập email đã đăng ký. Chúng tôi sẽ gửi một mã số để đặt lại mật khẩu.',
                style: TextStyle(color: p.textSub),
              ),
              const SizedBox(height: 20),
              TextFormField(
                controller: _email,
                enabled: !_codeSent,
                keyboardType: TextInputType.emailAddress,
                autofillHints: const [AutofillHints.email],
                decoration: const InputDecoration(labelText: 'Email', prefixIcon: Icon(Icons.mail_outline)),
                validator: (v) {
                  final t = (v ?? '').trim();
                  if (t.isEmpty) return 'Nhập email';
                  if (!t.contains('@') || !t.contains('.')) return 'Email không hợp lệ';
                  return null;
                },
              ),
              if (_codeSent) ...[
                const SizedBox(height: 12),
                TextFormField(
                  controller: _code,
                  keyboardType: TextInputType.number,
                  autofillHints: const [AutofillHints.oneTimeCode],
                  decoration: const InputDecoration(labelText: 'Mã trong email', prefixIcon: Icon(Icons.pin_outlined)),
                  // Supabase cho chỉnh độ dài mã (6-10 số) — không ép cứng 6.
                  validator: (v) => RegExp(r'^\d{6,10}$').hasMatch((v ?? '').trim()) ? null : 'Nhập đủ mã số trong email',
                ),
                const SizedBox(height: 12),
                PasswordField(
                  controller: _pass,
                  label: 'Mật khẩu mới',
                  textInputAction: TextInputAction.next,
                  autofillHints: const [AutofillHints.newPassword],
                  validator: validateNewPassword,
                ),
                const SizedBox(height: 12),
                PasswordField(
                  controller: _pass2,
                  label: 'Nhập lại mật khẩu mới',
                  autofillHints: const [AutofillHints.newPassword],
                  validator: (v) => v == _pass.text ? null : 'Hai mật khẩu không khớp',
                  onSubmitted: (_) => _busy ? null : _reset(),
                ),
              ],
              if (_error != null) ...[
                const SizedBox(height: 16),
                Text(_error!, style: const TextStyle(color: Colors.redAccent)),
              ],
              const SizedBox(height: 24),
              FilledButton(
                onPressed: _busy ? null : (_codeSent ? _reset : _sendCode),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  child: _busy
                      ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                      : Text(_codeSent ? 'Đặt mật khẩu mới' : 'Gửi mã'),
                ),
              ),
              if (_codeSent)
                TextButton(
                  onPressed: _busy ? null : _sendCode,
                  child: const Text('Gửi lại mã'),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
