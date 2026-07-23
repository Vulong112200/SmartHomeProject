import 'package:flutter/material.dart';

import '../core/vendor_api.dart';
import '../theme/app_colors.dart';

/// Màn "Thêm thiết bị": khám phá thiết bị từ tài khoản nhà cung cấp rồi cho
/// người dùng chọn cái nào để thêm vào app (self-service).
///   - VeSync: nhập email/pass -> tự liệt kê -> chọn.
///   - Tuya: hướng dẫn liên kết QR -> tải danh sách (cần admin đã gán) -> chọn.
class AddDeviceScreen extends StatefulWidget {
  const AddDeviceScreen({super.key});

  @override
  State<AddDeviceScreen> createState() => _AddDeviceScreenState();
}

class _AddDeviceScreenState extends State<AddDeviceScreen> {
  String? _path; // null | 'vesync' | 'tuya'

  final _email = TextEditingController();
  final _password = TextEditingController();

  bool _loading = false;
  String? _error;
  List<Map<String, dynamic>> _discovered = [];
  final Set<String> _selected = {};
  Map<String, dynamic>? _tuyaInfo;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  void _reset() {
    setState(() {
      _path = null;
      _error = null;
      _discovered = [];
      _selected.clear();
      _tuyaInfo = null;
    });
  }

  Future<void> _vesyncConnect() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final (data, err) = await VendorApi.vesyncConnect(_email.text, _password.text);
    if (!mounted) return;
    setState(() {
      _loading = false;
      _error = err;
      _discovered = data ?? [];
      _selected
        ..clear()
        ..addAll(_discovered.map((d) => '${d['id']}')); // mặc định chọn hết
    });
  }

  Future<void> _openTuya() async {
    setState(() {
      _path = 'tuya';
      _loading = true;
      _error = null;
    });
    final (info, err) = await VendorApi.tuyaLinkInfo();
    if (!mounted) return;
    setState(() {
      _loading = false;
      _tuyaInfo = info;
      _error = err;
    });
  }

  Future<void> _tuyaDiscover() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final (data, err) = await VendorApi.tuyaDiscover();
    if (!mounted) return;
    setState(() {
      _loading = false;
      _error = err;
      _discovered = data ?? [];
      _selected
        ..clear()
        ..addAll(_discovered.map((d) => '${d['id']}'));
    });
  }

  Future<void> _import() async {
    final items = _discovered
        .where((d) => _selected.contains('${d['id']}'))
        .map((d) => {
              'id': '${d['id']}',
              'name': d['name'] ?? d['id'],
              'brand': _path == 'vesync' ? 'vesync' : (d['suggested_brand'] ?? 'tuya'),
              'category': d['category'],
            })
        .toList();
    if (items.isEmpty) {
      setState(() => _error = 'Chưa chọn thiết bị nào.');
      return;
    }
    setState(() => _loading = true);
    final err = await VendorApi.importDevices(items);
    if (!mounted) return;
    setState(() => _loading = false);
    if (err == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Đã thêm ${items.length} thiết bị'), backgroundColor: AppColors.success),
      );
      Navigator.of(context).pop();
    } else {
      setState(() => _error = err);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        backgroundColor: AppColors.surface,
        title: const Text('Thêm thiết bị'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => _path == null ? Navigator.pop(context) : _reset(),
        ),
      ),
      body: SafeArea(
        child: _path == null ? _buildChooser() : _buildFlow(),
      ),
    );
  }

  Widget _buildChooser() {
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        const Text('Chọn nền tảng để kết nối',
            style: TextStyle(color: AppColors.textMain, fontSize: 18, fontWeight: FontWeight.bold)),
        const SizedBox(height: 16),
        _brandCard('VeSync', 'Máy lọc không khí / quạt — nhập email & mật khẩu tài khoản VeSync.',
            Icons.air, () => setState(() => _path = 'vesync')),
        const SizedBox(height: 12),
        _brandCard('Tuya / Smart Life', 'Cửa cuốn, máy cho ăn... — liên kết tài khoản qua mã QR.',
            Icons.sensors, _openTuya),
      ],
    );
  }

  Widget _brandCard(String title, String sub, IconData icon, VoidCallback onTap) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(16),
      child: Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(color: AppColors.card, borderRadius: BorderRadius.circular(16)),
        child: Row(
          children: [
            Icon(icon, color: AppColors.primary, size: 32),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: const TextStyle(color: AppColors.textMain, fontSize: 16, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 4),
                  Text(sub, style: const TextStyle(color: AppColors.textSub, fontSize: 12)),
                ],
              ),
            ),
            const Icon(Icons.chevron_right, color: AppColors.textSub),
          ],
        ),
      ),
    );
  }

  Widget _buildFlow() {
    return Column(
      children: [
        Expanded(
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              if (_path == 'vesync') ..._vesyncSection(),
              if (_path == 'tuya') ..._tuyaSection(),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(_error!, style: const TextStyle(color: Colors.redAccent)),
              ],
              if (_discovered.isNotEmpty) ..._deviceList(),
            ],
          ),
        ),
        if (_discovered.isNotEmpty) _importBar(),
      ],
    );
  }

  List<Widget> _vesyncSection() {
    return [
      const Text('Đăng nhập VeSync',
          style: TextStyle(color: AppColors.textMain, fontSize: 18, fontWeight: FontWeight.bold)),
      const SizedBox(height: 4),
      const Text('App chỉ dùng để lấy danh sách thiết bị; mật khẩu được mã hóa khi lưu.',
          style: TextStyle(color: AppColors.textSub, fontSize: 12)),
      const SizedBox(height: 16),
      _input(_email, 'Email VeSync', Icons.email_outlined),
      const SizedBox(height: 12),
      _input(_password, 'Mật khẩu', Icons.lock_outline, obscure: true),
      const SizedBox(height: 16),
      _primaryButton(_discovered.isEmpty ? 'Kết nối & lấy thiết bị' : 'Kết nối lại', _vesyncConnect),
    ];
  }

  List<Widget> _tuyaSection() {
    final steps = (_tuyaInfo?['steps'] as List?)?.cast<dynamic>() ?? const [];
    return [
      const Text('Liên kết Tuya / Smart Life',
          style: TextStyle(color: AppColors.textMain, fontSize: 18, fontWeight: FontWeight.bold)),
      const SizedBox(height: 12),
      for (int i = 0; i < steps.length; i++)
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('${i + 1}. ', style: const TextStyle(color: AppColors.primary)),
              Expanded(child: Text('${steps[i]}', style: const TextStyle(color: AppColors.textSub))),
            ],
          ),
        ),
      if (_tuyaInfo?['note'] != null) ...[
        const SizedBox(height: 8),
        Text('${_tuyaInfo!['note']}',
            style: const TextStyle(color: AppColors.textSub, fontSize: 12, fontStyle: FontStyle.italic)),
      ],
      const SizedBox(height: 16),
      _primaryButton('Tải danh sách thiết bị', _tuyaDiscover),
    ];
  }

  List<Widget> _deviceList() {
    return [
      const SizedBox(height: 20),
      Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text('Thiết bị tìm thấy (${_discovered.length})',
              style: const TextStyle(color: AppColors.textMain, fontWeight: FontWeight.bold)),
          TextButton(
            onPressed: () => setState(() {
              if (_selected.length == _discovered.length) {
                _selected.clear();
              } else {
                _selected
                  ..clear()
                  ..addAll(_discovered.map((d) => '${d['id']}'));
              }
            }),
            child: Text(_selected.length == _discovered.length ? 'Bỏ chọn hết' : 'Chọn hết',
                style: const TextStyle(color: AppColors.primary)),
          ),
        ],
      ),
      for (final d in _discovered)
        CheckboxListTile(
          value: _selected.contains('${d['id']}'),
          onChanged: (v) => setState(() {
            final id = '${d['id']}';
            v == true ? _selected.add(id) : _selected.remove(id);
          }),
          activeColor: AppColors.primary,
          title: Text('${d['name'] ?? d['id']}', style: const TextStyle(color: AppColors.textMain)),
          subtitle: Text(
            _path == 'vesync'
                ? '${d['device_type'] ?? ''}'
                : 'Loại: ${d['category'] ?? '?'} • ${d['suggested_brand'] ?? 'tuya'}',
            style: const TextStyle(color: AppColors.textSub, fontSize: 12),
          ),
        ),
    ];
  }

  Widget _importBar() {
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: SizedBox(
          height: 50,
          width: double.infinity,
          child: ElevatedButton(
            onPressed: _loading ? null : _import,
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.primary,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            ),
            child: Text('Thêm ${_selected.length} thiết bị',
                style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
          ),
        ),
      ),
    );
  }

  Widget _input(TextEditingController c, String label, IconData icon, {bool obscure = false}) {
    return TextField(
      controller: c,
      obscureText: obscure,
      style: const TextStyle(color: AppColors.textMain),
      decoration: InputDecoration(
        labelText: label,
        labelStyle: const TextStyle(color: AppColors.textSub),
        prefixIcon: Icon(icon, color: AppColors.textSub),
        filled: true,
        fillColor: AppColors.card,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: BorderSide.none),
      ),
    );
  }

  Widget _primaryButton(String label, VoidCallback onTap) {
    return SizedBox(
      height: 50,
      child: ElevatedButton(
        onPressed: _loading ? null : onTap,
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.primary,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        ),
        child: _loading
            ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white))
            : Text(label, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
      ),
    );
  }
}
