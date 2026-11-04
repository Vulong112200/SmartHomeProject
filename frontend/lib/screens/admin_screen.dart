import 'package:flutter/material.dart';

import '../core/auth_service.dart';
import '../core/device_api.dart';
import '../core/device_type.dart';
import '../core/household_api.dart';
import '../theme/app_colors.dart';

/// Màn hình quản trị nhà — chỉ chủ nhà vào được.
///
/// Hai tab:
///   • Thành viên — duyệt người mới, đổi vai, cấp khu.
///   • Khu vực    — tạo/sửa/xóa phòng, sắp thứ tự, gán thiết bị vào phòng.
class AdminScreen extends StatefulWidget {
  final HouseholdProfile profile;
  const AdminScreen({super.key, required this.profile});

  @override
  State<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends State<AdminScreen> with SingleTickerProviderStateMixin {
  late final TabController _tabs = TabController(length: 2, vsync: this);

  List<Zone> _zones = [];
  List<Member> _members = [];
  List<Map<String, dynamic>> _devices = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }

  Future<void> _reload() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final results = await Future.wait([
      HouseholdApi.fetchZones(),
      HouseholdApi.fetchMembers(),
      DeviceApi.fetchDevices(),
    ]);
    if (!mounted) return;
    final zones = results[0] as List<Zone>?;
    final members = results[1] as List<Member>?;
    final devices = results[2] as List<Map<String, dynamic>>?;
    setState(() {
      _loading = false;
      if (zones == null || members == null) {
        _error = 'Không tải được dữ liệu. Kiểm tra kết nối rồi thử lại.';
        return;
      }
      _zones = zones;
      _members = members;
      _devices = devices ?? [];
    });
  }

  void _toast(String msg, {bool error = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(msg),
      backgroundColor: error ? Colors.redAccent : null,
    ));
  }

  /// Chạy một hành động ghi rồi tải lại. Trả true nếu thành công.
  Future<bool> _run(Future<String?> action, String okMessage) async {
    final err = await action;
    if (err != null) {
      _toast(err, error: true);
      return false;
    }
    _toast(okMessage);
    await _reload();
    return true;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: context.palette.background,
      appBar: AppBar(
        title: const Text('Quản trị nhà'),
        backgroundColor: context.palette.surface,
        bottom: TabBar(
          controller: _tabs,
          indicatorColor: context.palette.primary,
          tabs: const [
            Tab(icon: Icon(Icons.people_outline), text: 'Thành viên'),
            Tab(icon: Icon(Icons.meeting_room_outlined), text: 'Khu vực'),
          ],
        ),
        actions: [
          IconButton(
            onPressed: _loading ? null : _reload,
            icon: const Icon(Icons.refresh),
            tooltip: 'Tải lại',
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? _ErrorView(message: _error!, onRetry: _reload)
              : TabBarView(
                  controller: _tabs,
                  children: [_membersTab(), _zonesTab()],
                ),
    );
  }

  // =======================================================
  // Tab THÀNH VIÊN
  // =======================================================
  Widget _membersTab() {
    // Người chờ duyệt ghim lên đầu — đó là việc cần làm, không phải danh sách
    // để cuộn tìm. Còn lại sắp theo email cho ổn định.
    final pending = _members.where((m) => m.isPending).toList();
    final others = _members.where((m) => !m.isPending).toList()
      ..sort((a, b) => a.email.compareTo(b.email));

    if (_members.isEmpty) {
      return const _EmptyView(
        icon: Icons.people_outline,
        title: 'Chưa có thành viên nào',
        subtitle: 'Người nhà tự đăng ký trong app, rồi hiện ở đây để bạn duyệt.',
      );
    }

    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (pending.isNotEmpty) ...[
            const _SectionLabel('Chờ bạn duyệt'),
            ...pending.map(_memberTile),
            const SizedBox(height: 20),
          ],
          const _SectionLabel('Thành viên'),
          ...others.map(_memberTile),
        ],
      ),
    );
  }

  Widget _memberTile(Member m) {
    const roleLabel = {
      'owner': 'Chủ nhà',
      'adult': 'Người lớn',
      'kid': 'Trẻ em',
      'guest': 'Khách',
    };
    final isMe = m.userId == widget.profile.userId;
    final zoneNames = _zones
        .where((z) => m.zoneIds.contains(z.id))
        .map((z) => z.name)
        .join(', ');

    String subtitle;
    if (m.status == 'blocked') {
      subtitle = 'Đã bị chặn';
    } else if (m.isPending) {
      subtitle = 'Chờ duyệt';
    } else if (m.seesAllZones) {
      subtitle = 'Thấy mọi khu vực';
    } else {
      subtitle = zoneNames.isEmpty ? 'Chưa được cấp khu nào' : 'Khu: $zoneNames';
    }

    return Card(
      color: context.palette.surface,
      margin: const EdgeInsets.only(bottom: 10),
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: m.isPending
              ? Colors.orangeAccent.withValues(alpha: 0.2)
              : context.palette.primary.withValues(alpha: 0.2),
          child: Icon(
            m.status == 'blocked'
                ? Icons.block
                : m.isPending
                    ? Icons.hourglass_top
                    : Icons.person,
            color: m.isPending ? Colors.orangeAccent : context.palette.primary,
            size: 20,
          ),
        ),
        title: Row(
          children: [
            Flexible(
              child: Text(
                m.displayName.isEmpty ? m.email : m.displayName,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            if (isMe)
              Padding(
                padding: const EdgeInsets.only(left: 6),
                child: Text('(bạn)', style: TextStyle(color: context.palette.textSub, fontSize: 12)),
              ),
          ],
        ),
        subtitle: Text(subtitle, style: const TextStyle(fontSize: 12)),
        trailing: Chip(
          label: Text(roleLabel[m.role] ?? m.role, style: const TextStyle(fontSize: 11)),
          visualDensity: VisualDensity.compact,
          padding: EdgeInsets.zero,
        ),
        onTap: () => _editMember(m),
      ),
    );
  }

  Future<void> _editMember(Member m) async {
    final isMe = m.userId == widget.profile.userId;
    // Chủ nhà đang hoạt động cuối cùng: hạ vai hoặc chặn là nhà không còn ai
    // quản trị. API cũng chặn, nhưng chặn ở UI để không đưa ra lựa chọn chết.
    final activeOwners =
        _members.where((x) => x.role == 'owner' && x.status == 'active').length;
    final isLastOwner = m.role == 'owner' && m.status == 'active' && activeOwners <= 1;

    var role = m.role;
    var status = m.status;
    var zoneIds = List<int>.from(m.zoneIds);

    final saved = await showModalBottomSheet<bool>(
      context: context,
      backgroundColor: context.palette.surface,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (sheetCtx) => StatefulBuilder(
        builder: (sheetCtx, setSheet) {
          final locked = isMe || isLastOwner;
          final seesAll = role == 'owner' || role == 'adult';

          return Padding(
            padding: EdgeInsets.only(
              left: 20,
              right: 20,
              top: 20,
              bottom: MediaQuery.of(sheetCtx).viewInsets.bottom + 20,
            ),
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(m.email, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 4),
                  if (locked)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Text(
                        isMe
                            ? 'Không thể tự đổi vai hoặc tự chặn chính mình.'
                            : 'Đây là chủ nhà duy nhất đang hoạt động — hãy chỉ '
                                'định chủ nhà khác trước khi đổi.',
                        style: const TextStyle(color: Colors.orangeAccent, fontSize: 12),
                      ),
                    ),

                  const SizedBox(height: 12),
                  Text('Vai trò', style: TextStyle(color: context.palette.textSub, fontSize: 12)),
                  const SizedBox(height: 6),
                  Wrap(
                    spacing: 8,
                    children: [
                      for (final entry in const {
                        'owner': 'Chủ nhà',
                        'adult': 'Người lớn',
                        'kid': 'Trẻ em',
                        'guest': 'Khách',
                      }.entries)
                        ChoiceChip(
                          label: Text(entry.value),
                          selected: role == entry.key,
                          onSelected: locked
                              ? null
                              : (_) => setSheet(() => role = entry.key),
                        ),
                    ],
                  ),

                  const SizedBox(height: 16),
                  Text('Trạng thái', style: TextStyle(color: context.palette.textSub, fontSize: 12)),
                  const SizedBox(height: 6),
                  Wrap(
                    spacing: 8,
                    children: [
                      for (final entry in const {
                        'active': 'Hoạt động',
                        'pending': 'Chờ duyệt',
                        'blocked': 'Chặn',
                      }.entries)
                        ChoiceChip(
                          label: Text(entry.value),
                          selected: status == entry.key,
                          onSelected: locked
                              ? null
                              : (_) => setSheet(() => status = entry.key),
                        ),
                    ],
                  ),

                  const SizedBox(height: 16),
                  Text('Khu vực được dùng',
                      style: TextStyle(color: context.palette.textSub, fontSize: 12)),
                  const SizedBox(height: 6),
                  if (seesAll)
                    // Không hiện ô tick cho owner/adult: họ thấy mọi khu theo
                    // luật vai, tick vào chẳng thay đổi gì mà lại gây hiểu nhầm.
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      child: Text(
                        'Vai này thấy mọi khu vực, không cần cấp riêng.',
                        style: TextStyle(color: context.palette.textSub, fontSize: 12),
                      ),
                    )
                  else if (_zones.isEmpty)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 8),
                      child: Text(
                        'Chưa có khu vực nào. Tạo khu ở tab Khu vực trước.',
                        style: TextStyle(color: Colors.orangeAccent, fontSize: 12),
                      ),
                    )
                  else
                    Wrap(
                      spacing: 8,
                      children: [
                        for (final z in _zones)
                          FilterChip(
                            label: Text(z.name),
                            selected: zoneIds.contains(z.id),
                            onSelected: (on) => setSheet(() {
                              if (on) {
                                zoneIds.add(z.id);
                              } else {
                                zoneIds.remove(z.id);
                              }
                            }),
                          ),
                      ],
                    ),

                  const SizedBox(height: 24),
                  Row(
                    children: [
                      if (m.isPending && !locked)
                        Expanded(
                          child: FilledButton.icon(
                            icon: const Icon(Icons.check),
                            label: const Text('Duyệt'),
                            onPressed: () {
                              setSheet(() => status = 'active');
                            },
                          ),
                        ),
                      if (m.isPending && !locked) const SizedBox(width: 10),
                      Expanded(
                        child: FilledButton(
                          onPressed: locked
                              ? null
                              : () => Navigator.pop(sheetCtx, true),
                          child: const Text('Lưu'),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Center(
                    child: TextButton(
                      onPressed: () => Navigator.pop(sheetCtx),
                      child: const Text('Hủy'),
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );

    if (saved != true) return;
    await _run(
      HouseholdApi.updateMember(
        m.userId,
        role: role,
        status: status,
        // owner/adult không dùng grant — gửi list rỗng để không để lại hàng
        // thừa nếu sau này họ bị hạ xuống kid.
        zoneIds: (role == 'owner' || role == 'adult') ? const [] : zoneIds,
      ),
      'Đã cập nhật ${m.email}',
    );
  }

  // =======================================================
  // Tab KHU VỰC
  // =======================================================
  Widget _zonesTab() {
    // Pseudo-zone "Chưa phân khu" luôn ở CUỐI: thiết bị mới import rơi vào
    // zone_id NULL, không hiện ở đâu thì chủ nhà sẽ không biết chúng tồn tại.
    final unassigned = _devices.where((d) => d['zone_id'] == null).toList();

    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_zones.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 24),
              child: Text(
                'Chưa có khu vực nào. Thêm phòng để chia quyền cho trẻ em và khách.',
                style: TextStyle(color: context.palette.textSub),
                textAlign: TextAlign.center,
              ),
            ),
          ..._zones.map(_zoneCard),
          if (unassigned.isNotEmpty) ...[
            const SizedBox(height: 8),
            _unassignedCard(unassigned),
          ],
          const SizedBox(height: 16),
          OutlinedButton.icon(
            onPressed: _createZone,
            icon: const Icon(Icons.add),
            label: const Text('Thêm khu vực'),
          ),
          const SizedBox(height: 80),
        ],
      ),
    );
  }

  Widget _zoneCard(Zone z) {
    final devices = _devices.where((d) => d['zone_id'] == z.id).toList();
    return Card(
      color: context.palette.surface,
      margin: const EdgeInsets.only(bottom: 10),
      child: ExpansionTile(
        leading: Icon(Icons.meeting_room_outlined, color: context.palette.primary),
        title: Text(z.name),
        subtitle: Text('${devices.length} thiết bị', style: const TextStyle(fontSize: 12)),
        trailing: PopupMenuButton<String>(
          color: context.palette.surface,
          onSelected: (v) {
            if (v == 'rename') _renameZone(z);
            if (v == 'delete') _deleteZone(z, devices.length);
          },
          itemBuilder: (_) => const [
            PopupMenuItem(value: 'rename', child: Text('Đổi tên')),
            PopupMenuItem(value: 'delete', child: Text('Xóa khu')),
          ],
        ),
        children: [
          if (devices.isEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text('Chưa có thiết bị nào trong khu này.',
                    style: TextStyle(color: context.palette.textSub, fontSize: 12)),
              ),
            ),
          ...devices.map((d) => _deviceRow(d, currentZoneId: z.id)),
        ],
      ),
    );
  }

  Widget _unassignedCard(List<Map<String, dynamic>> devices) {
    return Card(
      color: context.palette.surface,
      margin: const EdgeInsets.only(bottom: 10),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: Colors.orangeAccent.withValues(alpha: 0.5)),
      ),
      child: ExpansionTile(
        initiallyExpanded: true,
        leading: const Icon(Icons.inbox_outlined, color: Colors.orangeAccent),
        title: const Text('Chưa phân khu'),
        subtitle: Text(
          '${devices.length} thiết bị — chỉ chủ nhà và người lớn thấy được',
          style: const TextStyle(fontSize: 12),
        ),
        children: devices.map((d) => _deviceRow(d, currentZoneId: null)).toList(),
      ),
    );
  }

  Widget _deviceRow(Map<String, dynamic> d, {required int? currentZoneId}) {
    final categoryLabel = deviceCategoryLabels[d['category']] ?? 'Loại: tự đoán theo tên';
    return ListTile(
      dense: true,
      leading: Icon(Icons.devices_other, size: 20, color: context.palette.textSub),
      title: Text('${d['name']}', style: const TextStyle(fontSize: 14)),
      subtitle: Text('${d['brand']} • $categoryLabel', style: const TextStyle(fontSize: 11)),
      onTap: () => _setCategory(d),
      trailing: TextButton(
        onPressed: () => _moveDevice(d, currentZoneId),
        child: const Text('Chuyển khu'),
      ),
    );
  }

  Future<void> _moveDevice(Map<String, dynamic> device, int? currentZoneId) async {
    final chosen = await showModalBottomSheet<Object?>(
      context: context,
      backgroundColor: context.palette.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.all(16),
              child: Text('Chuyển "${device['name']}" tới',
                  style: const TextStyle(fontWeight: FontWeight.bold)),
            ),
            for (final z in _zones)
              ListTile(
                leading: const Icon(Icons.meeting_room_outlined),
                title: Text(z.name),
                trailing: z.id == currentZoneId ? const Icon(Icons.check) : null,
                onTap: () => Navigator.pop(ctx, z.id),
              ),
            ListTile(
              leading: const Icon(Icons.inbox_outlined, color: Colors.orangeAccent),
              title: const Text('Chưa phân khu'),
              trailing: currentZoneId == null ? const Icon(Icons.check) : null,
              onTap: () => Navigator.pop(ctx, 'none'),
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );

    if (chosen == null) return;
    if (chosen == 'none') {
      if (currentZoneId == null) return;
      await _run(
        HouseholdApi.updateDevice('${device['id']}', clearZone: true),
        'Đã chuyển về Chưa phân khu',
      );
      return;
    }
    if (chosen == currentZoneId) return;
    await _run(
      HouseholdApi.updateDevice('${device['id']}', zoneId: chosen as int),
      'Đã chuyển khu',
    );
  }

  Future<void> _setCategory(Map<String, dynamic> device) async {
    final current = device['category'] as String?;
    final chosen = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: context.palette.surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.all(16),
              child: Text('Loại của "${device['name']}"',
                  style: const TextStyle(fontWeight: FontWeight.bold)),
            ),
            for (final e in deviceCategoryLabels.entries)
              ListTile(
                title: Text(e.value),
                trailing: e.key == current ? const Icon(Icons.check) : null,
                onTap: () => Navigator.pop(ctx, e.key),
              ),
            ListTile(
              leading: const Icon(Icons.auto_fix_high_outlined),
              title: const Text('Tự đoán theo tên'),
              trailing: current == null ? const Icon(Icons.check) : null,
              onTap: () => Navigator.pop(ctx, 'none'),
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );

    if (chosen == null) return;
    if (chosen == 'none') {
      if (current == null) return;
      await _run(
        HouseholdApi.updateDevice('${device['id']}', clearCategory: true),
        'Đã chuyển về tự đoán loại',
      );
      return;
    }
    if (chosen == current) return;
    await _run(
      HouseholdApi.updateDevice('${device['id']}', category: chosen),
      'Đã đặt loại: ${deviceCategoryLabels[chosen]}',
    );
  }

  Future<void> _createZone() async {
    final name = await _askText(title: 'Tên khu vực mới', hint: 'Phòng khách');
    if (name == null || name.trim().isEmpty) return;
    // sort_order nối tiếp để khu mới xuống cuối, không chen giữa.
    final nextOrder = _zones.isEmpty
        ? 0
        : _zones.map((z) => z.sortOrder).reduce((a, b) => a > b ? a : b) + 1;
    await _run(
      HouseholdApi.createZone(name.trim(), sortOrder: nextOrder),
      'Đã tạo khu "${name.trim()}"',
    );
  }

  Future<void> _renameZone(Zone z) async {
    final name = await _askText(title: 'Đổi tên khu vực', initial: z.name);
    if (name == null || name.trim().isEmpty || name.trim() == z.name) return;
    await _run(
      HouseholdApi.updateZone(z.id, {'name': name.trim()}),
      'Đã đổi tên khu',
    );
  }

  Future<void> _deleteZone(Zone z, int deviceCount) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: context.palette.surface,
        title: Text('Xóa khu "${z.name}"?'),
        content: Text(
          deviceCount == 0
              ? 'Khu này không có thiết bị nào.'
              : '$deviceCount thiết bị sẽ chuyển về mục "Chưa phân khu", '
                  'KHÔNG bị xóa. Ai đang được cấp khu này sẽ mất quyền với chúng.',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Hủy')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Colors.redAccent),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Xóa'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    await _run(HouseholdApi.deleteZone(z.id), 'Đã xóa khu');
  }

  Future<String?> _askText({
    required String title,
    String? hint,
    String? initial,
  }) {
    final ctrl = TextEditingController(text: initial);
    return showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: context.palette.surface,
        title: Text(title),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          decoration: InputDecoration(hintText: hint),
          onSubmitted: (v) => Navigator.pop(ctx, v),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Hủy')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, ctrl.text),
            child: const Text('Lưu'),
          ),
        ],
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  final String text;
  const _SectionLabel(this.text);

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Text(
          text.toUpperCase(),
          style: TextStyle(
            color: context.palette.textSub,
            fontSize: 11,
            letterSpacing: 1.1,
            fontWeight: FontWeight.bold,
          ),
        ),
      );
}

class _EmptyView extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  const _EmptyView({required this.icon, required this.title, required this.subtitle});

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 56, color: context.palette.textSub),
              const SizedBox(height: 16),
              Text(title, style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              Text(subtitle,
                  textAlign: TextAlign.center,
                  style: TextStyle(color: context.palette.textSub, fontSize: 13)),
            ],
          ),
        ),
      );
}

class _ErrorView extends StatelessWidget {
  final String message;
  final Future<void> Function() onRetry;
  const _ErrorView({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.cloud_off, size: 56, color: context.palette.textSub),
              const SizedBox(height: 16),
              Text(message, textAlign: TextAlign.center),
              const SizedBox(height: 20),
              FilledButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: const Text('Thử lại'),
              ),
            ],
          ),
        ),
      );
}
