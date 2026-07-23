import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../core/auth_service.dart';
import '../theme/app_colors.dart';

/// Màn đăng nhập / đăng ký (Supabase Auth email + mật khẩu).
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _name = TextEditingController();
  bool _isSignUp = false;
  bool _loading = false;
  bool _obscure = true;
  String? _error;
  String? _info;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _name.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final email = _email.text.trim();
    final pass = _password.text;
    if (email.isEmpty || pass.length < 6) {
      setState(() => _error = 'Nhập email hợp lệ và mật khẩu ≥ 6 ký tự.');
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
      _info = null;
    });
    try {
      if (_isSignUp) {
        await AuthService.signUp(email, pass,
            displayName: _name.text.trim().isEmpty ? null : _name.text.trim());
        // Nếu bật xác nhận email, session sẽ null cho tới khi user confirm.
        if (!AuthService.isLoggedIn) {
          setState(() => _info = 'Đã tạo tài khoản. Kiểm tra email để xác nhận rồi đăng nhập.');
        }
      } else {
        await AuthService.signIn(email, pass);
      }
      // AuthGate tự chuyển màn khi session thay đổi.
    } on AuthException catch (e) {
      setState(() => _error = e.message);
    } catch (e) {
      setState(() => _error = 'Lỗi: $e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Container(
                    width: 72,
                    height: 72,
                    alignment: Alignment.center,
                    decoration: const BoxDecoration(
                      gradient: AppColors.primaryGradient,
                      shape: BoxShape.circle,
                    ),
                    child: const Icon(Icons.home_rounded, color: Colors.white, size: 40),
                  ),
                  const SizedBox(height: 20),
                  Text(
                    _isSignUp ? 'Tạo tài khoản' : 'Đăng nhập',
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                        color: AppColors.textMain,
                        fontSize: 26,
                        fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 4),
                  const Text('Smart Home',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: AppColors.textSub)),
                  const SizedBox(height: 28),
                  if (_isSignUp) ...[
                    _field(_name, 'Tên hiển thị (tùy chọn)', Icons.person_outline),
                    const SizedBox(height: 14),
                  ],
                  _field(_email, 'Email', Icons.email_outlined,
                      keyboardType: TextInputType.emailAddress),
                  const SizedBox(height: 14),
                  _field(_password, 'Mật khẩu', Icons.lock_outline,
                      obscure: _obscure,
                      suffix: IconButton(
                        icon: Icon(_obscure ? Icons.visibility_off : Icons.visibility,
                            color: AppColors.textSub),
                        onPressed: () => setState(() => _obscure = !_obscure),
                      )),
                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    Text(_error!, style: const TextStyle(color: Colors.redAccent)),
                  ],
                  if (_info != null) ...[
                    const SizedBox(height: 12),
                    Text(_info!, style: const TextStyle(color: AppColors.success)),
                  ],
                  const SizedBox(height: 22),
                  SizedBox(
                    height: 52,
                    child: ElevatedButton(
                      onPressed: _loading ? null : _submit,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppColors.primary,
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14)),
                      ),
                      child: _loading
                          ? const SizedBox(
                              width: 22,
                              height: 22,
                              child: CircularProgressIndicator(
                                  strokeWidth: 2.5, color: Colors.white))
                          : Text(_isSignUp ? 'Đăng ký' : 'Đăng nhập',
                              style: const TextStyle(
                                  fontSize: 16, fontWeight: FontWeight.w600)),
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextButton(
                    onPressed: _loading
                        ? null
                        : () => setState(() {
                              _isSignUp = !_isSignUp;
                              _error = null;
                              _info = null;
                            }),
                    child: Text(
                      _isSignUp
                          ? 'Đã có tài khoản? Đăng nhập'
                          : 'Chưa có tài khoản? Đăng ký',
                      style: const TextStyle(color: AppColors.primary),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _field(TextEditingController c, String label, IconData icon,
      {bool obscure = false,
      TextInputType? keyboardType,
      Widget? suffix}) {
    return TextField(
      controller: c,
      obscureText: obscure,
      keyboardType: keyboardType,
      style: const TextStyle(color: AppColors.textMain),
      decoration: InputDecoration(
        labelText: label,
        labelStyle: const TextStyle(color: AppColors.textSub),
        prefixIcon: Icon(icon, color: AppColors.textSub),
        suffixIcon: suffix,
        filled: true,
        fillColor: AppColors.card,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: BorderSide.none,
        ),
      ),
    );
  }
}
