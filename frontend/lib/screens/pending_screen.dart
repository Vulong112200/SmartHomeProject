import 'package:flutter/material.dart';

import '../core/auth_service.dart';
import '../theme/app_colors.dart';

/// Màn hình khi tài khoản chưa được chủ nhà thêm vào nhà (hoặc bị chặn).
///
/// Người lạ đăng nhập lần đầu được backend tạo thành `guest`/`pending`: đăng
/// nhập được, `/api/me` được, mọi endpoint khác 403. Không có màn này thì app
/// chỉ hiện một loạt lỗi 403 khó hiểu.
class PendingScreen extends StatelessWidget {
  final HouseholdProfile profile;
  final Future<void> Function() onRetry;
  final VoidCallback onSignOut;

  const PendingScreen({
    super.key,
    required this.profile,
    required this.onRetry,
    required this.onSignOut,
  });

  @override
  Widget build(BuildContext context) {
    final blocked = profile.isBlocked;
    return Scaffold(
      backgroundColor: context.palette.background,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  blocked ? Icons.block : Icons.hourglass_top_rounded,
                  size: 72,
                  color: blocked ? Colors.redAccent : context.palette.primary,
                ),
                const SizedBox(height: 20),
                Text(
                  blocked ? 'Tài khoản đã bị chặn' : 'Chưa thuộc nhà nào',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 12),
                Text(
                  blocked
                      ? 'Hãy liên hệ chủ nhà nếu bạn nghĩ đây là nhầm lẫn.'
                      : 'Tài khoản ${profile.email} đã được tạo. Hãy nhờ chủ nhà '
                          'vào Quản trị nhà → Thành viên, tìm email này và bấm '
                          '"Thêm vào nhà". Xong thì bấm Kiểm tra lại bên dưới.',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 32),
                if (!blocked)
                  FilledButton.icon(
                    onPressed: onRetry,
                    icon: const Icon(Icons.refresh),
                    label: const Text('Kiểm tra lại'),
                  ),
                const SizedBox(height: 8),
                TextButton.icon(
                  onPressed: onSignOut,
                  icon: const Icon(Icons.logout),
                  label: const Text('Đăng xuất'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Backend không trả lời (Render đang ngủ, mất mạng).
/// Tách riêng khỏi "chưa đăng nhập": đăng xuất người dùng chỉ vì rớt mạng là
/// sai — họ sẽ phải gõ lại mật khẩu mỗi lần vào thang máy.
class OfflineScreen extends StatelessWidget {
  final Future<void> Function() onRetry;
  final VoidCallback onSignOut;

  const OfflineScreen({super.key, required this.onRetry, required this.onSignOut});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: context.palette.background,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.cloud_off, size: 72, color: context.palette.primary),
                const SizedBox(height: 20),
                Text(
                  'Không kết nối được máy chủ',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 12),
                Text(
                  'Máy chủ có thể đang khởi động lại (mất khoảng 30-50 giây). '
                  'Bạn vẫn đang đăng nhập.',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 32),
                FilledButton.icon(
                  onPressed: onRetry,
                  icon: const Icon(Icons.refresh),
                  label: const Text('Thử lại'),
                ),
                const SizedBox(height: 8),
                TextButton(onPressed: onSignOut, child: const Text('Đăng xuất')),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
