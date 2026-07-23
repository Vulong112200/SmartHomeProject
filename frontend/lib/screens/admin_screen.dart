import 'package:flutter/material.dart';

import '../core/vendor_api.dart';
import '../theme/app_colors.dart';

/// Màn Quản trị (chỉ admin): xem người dùng + thiết bị của họ, và quản lý các
/// tài khoản Tuya đã liên kết (gán cho user, import thiết bị hộ).
class AdminScreen extends StatefulWidget {
  const AdminScreen({super.key});

  @override
  State<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends State<AdminScreen> {
  List<Map<String, dynamic>> _users = [];
  List<Map<String, dynamic>> _tuya = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadAll();
  }

  Future<void> _loadAll() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final (users, uerr) = await VendorApi.adminUsers();
    final (tuya, _) = await VendorApi.adminTuyaLinked(); // có thể lỗi nếu chưa cấu hình schema
    if (!mounted) return;
    setState(() {
      _users = users ?? [];
      _tuya = tuya ?? [];
      _error = uerr;
      _loading = false;
    });
  }

  Future<void> _showUserDevices(Map<String, dynamic> user) async {
    final (devices, err) = await VendorApi.adminUserDevices('${user['user_id']}');
    if (!mounted) return;
    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.surface,
      builder: (_) => Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('${user['email'] ?? user['user_id']}',
                style: const TextStyle(color: AppColors.textMain, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            if (err != null) Text(err, style: const TextStyle(color: Colors.redAccent)),
            if (devices != null && devices.isEmpty)
              const Text('Chưa có thiết bị.', style: TextStyle(color: AppColors.textSub)),
            if (devices != null)
              ...devices.map((d) => ListTile(
                    dense: true,
                    title: Text('${d['name']}', style: const TextStyle(color: AppColors.textMain)),
                    subtitle: Text('${d['brand']} • ${d['id']}',
                        style: const TextStyle(color: AppColors.textSub, fontSize: 12)),
                  )),
          ],
        ),
      ),
    );
  }

  Future<Map<String, dynamic>?> _pickUser() {
    return showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => SimpleDialog(
        backgroundColor: AppColors.surface,
        title: const Text('Chọn người dùng', style: TextStyle(color: AppColors.textMain)),
        children: _users
            .map((u) => SimpleDialogOption(
                  onPressed: () => Navigator.pop(context, u),
                  child: Text('${u['email'] ?? u['user_id']}',
                      style: const TextStyle(color: AppColors.textMain)),
                ))
            .toList(),
      ),
    );
  }

  Future<void> _assignTuya(Map<String, dynamic> account) async {
    final user = await _pickUser();
    if (user == null) return;
    final err = await VendorApi.adminAssignTuya('${user['user_id']}', '${account['uid']}');
    _toast(err ?? 'Đã gán tài khoản Tuya cho ${user['email'] ?? user['user_id']}',
        ok: err == null);
  }

  Future<void> _importTuyaToUser(Map<String, dynamic> account) async {
    final user = await _pickUser();
    if (user == null) return;
    final devices = ((account['devices'] as List?) ?? [])
        .map((d) => {
              'id': '${d['id']}',
              'name': d['name'] ?? d['id'],
              'brand': d['suggested_brand'] ?? 'tuya',
              'category': d['category'],
            })
        .toList();
    if (devices.isEmpty) {
      _toast('Tài khoản này không có thiết bị.', ok: false);
      return;
    }
    final err = await VendorApi.adminImportDevices('${user['user_id']}', devices);
    _toast(err ?? 'Đã thêm ${devices.length} thiết bị cho ${user['email'] ?? user['user_id']}',
        ok: err == null);
  }

  void _toast(String msg, {bool ok = true}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(msg),
      backgroundColor: ok ? AppColors.success : Colors.redAccent,
    ));
  }

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        backgroundColor: AppColors.background,
        appBar: AppBar(
          backgroundColor: AppColors.surface,
          title: const Text('Quản trị'),
          actions: [IconButton(onPressed: _loadAll, icon: const Icon(Icons.refresh))],
          bottom: const TabBar(
            labelColor: AppColors.primary,
            unselectedLabelColor: AppColors.textSub,
            indicatorColor: AppColors.primary,
            tabs: [Tab(text: 'Người dùng'), Tab(text: 'Tuya liên kết')],
          ),
        ),
        body: _loading
            ? const Center(child: CircularProgressIndicator(color: AppColors.primary))
            : TabBarView(children: [_usersTab(), _tuyaTab()]),
      ),
    );
  }

  Widget _usersTab() {
    if (_error != null) {
      return Center(child: Text(_error!, style: const TextStyle(color: Colors.redAccent)));
    }
    if (_users.isEmpty) {
      return const Center(child: Text('Chưa có người dùng.', style: TextStyle(color: AppColors.textSub)));
    }
    return ListView.builder(
      padding: const EdgeInsets.all(12),
      itemCount: _users.length,
      itemBuilder: (_, i) {
        final u = _users[i];
        return Card(
          color: AppColors.card,
          child: ListTile(
            leading: const Icon(Icons.person, color: AppColors.primary),
            title: Text('${u['email'] ?? u['display_name'] ?? u['user_id']}',
                style: const TextStyle(color: AppColors.textMain)),
            subtitle: Text('Vai trò: ${u['role'] ?? 'user'} • ${u['device_count'] ?? 0} thiết bị',
                style: const TextStyle(color: AppColors.textSub, fontSize: 12)),
            trailing: const Icon(Icons.chevron_right, color: AppColors.textSub),
            onTap: () => _showUserDevices(u),
          ),
        );
      },
    );
  }

  Widget _tuyaTab() {
    if (_tuya.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text(
            'Chưa có tài khoản Tuya liên kết (hoặc chưa cấu hình TUYA_APP_SCHEMA trên server).',
            textAlign: TextAlign.center,
            style: TextStyle(color: AppColors.textSub),
          ),
        ),
      );
    }
    return ListView.builder(
      padding: const EdgeInsets.all(12),
      itemCount: _tuya.length,
      itemBuilder: (_, i) {
        final a = _tuya[i];
        final devices = (a['devices'] as List?) ?? [];
        return Card(
          color: AppColors.card,
          child: ExpansionTile(
            iconColor: AppColors.primary,
            collapsedIconColor: AppColors.textSub,
            title: Text('UID: ${a['uid']}', style: const TextStyle(color: AppColors.textMain, fontSize: 13)),
            subtitle: Text('${devices.length} thiết bị', style: const TextStyle(color: AppColors.textSub, fontSize: 12)),
            children: [
              ...devices.map((d) => ListTile(
                    dense: true,
                    title: Text('${d['name'] ?? d['id']}', style: const TextStyle(color: AppColors.textMain)),
                    subtitle: Text('${d['category'] ?? ''} • ${d['suggested_brand'] ?? 'tuya'}',
                        style: const TextStyle(color: AppColors.textSub, fontSize: 12)),
                  )),
              OverflowBar(
                alignment: MainAxisAlignment.end,
                children: [
                  TextButton(onPressed: () => _assignTuya(a), child: const Text('Gán cho user')),
                  TextButton(onPressed: () => _importTuyaToUser(a), child: const Text('Thêm thiết bị cho user')),
                ],
              ),
            ],
          ),
        );
      },
    );
  }
}
