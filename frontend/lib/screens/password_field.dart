import 'package:flutter/material.dart';

/// Ô mật khẩu có nút con mắt ẩn/hiện — dùng chung cho đăng nhập, quên và đổi mật khẩu.
class PasswordField extends StatefulWidget {
  final TextEditingController controller;
  final String label;
  final String? Function(String?)? validator;
  final TextInputAction textInputAction;
  final ValueChanged<String>? onSubmitted;
  final Iterable<String> autofillHints;

  const PasswordField({
    super.key,
    required this.controller,
    this.label = 'Mật khẩu',
    this.validator,
    this.textInputAction = TextInputAction.done,
    this.onSubmitted,
    this.autofillHints = const [AutofillHints.password],
  });

  @override
  State<PasswordField> createState() => _PasswordFieldState();
}

class _PasswordFieldState extends State<PasswordField> {
  bool _obscure = true;

  @override
  Widget build(BuildContext context) {
    return TextFormField(
      controller: widget.controller,
      obscureText: _obscure,
      textInputAction: widget.textInputAction,
      autofillHints: widget.autofillHints,
      onFieldSubmitted: widget.onSubmitted,
      validator: widget.validator,
      decoration: InputDecoration(
        labelText: widget.label,
        prefixIcon: const Icon(Icons.lock_outline),
        suffixIcon: IconButton(
          tooltip: _obscure ? 'Hiện mật khẩu' : 'Ẩn mật khẩu',
          icon: Icon(_obscure ? Icons.visibility_off : Icons.visibility),
          onPressed: () => setState(() => _obscure = !_obscure),
        ),
      ),
    );
  }
}

/// Luật mật khẩu mới (khớp tối thiểu của Supabase: 6 ký tự).
String? validateNewPassword(String? v) {
  if ((v ?? '').isEmpty) return 'Nhập mật khẩu mới';
  if (v!.length < 6) return 'Mật khẩu tối thiểu 6 ký tự';
  return null;
}

/// Dịch lỗi tiếng Anh hay gặp của Supabase Auth sang tiếng Việt.
String friendlyAuthError(String raw) {
  final m = raw.toLowerCase();
  if (m.contains('invalid login credentials')) return 'Email hoặc mật khẩu không đúng.';
  if (m.contains('email not confirmed')) return 'Email chưa được xác nhận. Kiểm tra hộp thư của bạn.';
  if (m.contains('user already registered')) return 'Email này đã có tài khoản. Hãy đăng nhập.';
  if (m.contains('password should be at least')) return 'Mật khẩu quá ngắn (tối thiểu 6 ký tự).';
  if (m.contains('expired') || (m.contains('invalid') && (m.contains('otp') || m.contains('token')))) {
    return 'Mã không đúng hoặc đã hết hạn. Gửi lại mã mới.';
  }
  if (m.contains('rate limit') || m.contains('too many') || m.contains('security purposes')) {
    return 'Gửi quá nhiều lần. Đợi vài phút rồi thử lại.';
  }
  if (m.contains('same') && m.contains('password')) return 'Mật khẩu mới phải khác mật khẩu cũ.';
  return raw;
}
