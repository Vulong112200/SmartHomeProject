import 'package:flutter/material.dart';

import '../core/device_api.dart';
import '../core/history_api.dart';
import '../theme/app_colors.dart';

/// Lịch sử điều khiển: ai bấm, bấm từ đâu (app / widget / icon nhanh / giọng
/// nói / kịch bản / lịch hẹn) hoặc thay đổi ngoài app (nút vật lý, app Smart
/// Life...), và lúc nào. Mới nhất ở trên, nhóm theo ngày.
class HistoryScreen extends StatefulWidget {
  const HistoryScreen({super.key});

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  final List<HistoryEntry> _entries = [];
  List<Map<String, dynamic>> _devices = [];
  String? _deviceId; // null = mọi thiết bị
  bool _outsideOnly = false;
  bool _loading = true;
  bool _loadingMore = false;
  bool _hasMore = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    DeviceApi.fetchDevices().then((d) {
      if (mounted && d != null) setState(() => _devices = d);
    });
    _reload();
  }

  Future<void> _reload() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final page = await HistoryApi.fetch(deviceId: _deviceId);
    if (!mounted) return;
    setState(() {
      _loading = false;
      if (page == null) {
        _error = 'Không tải được lịch sử. Kiểm tra mạng rồi thử lại.';
        return;
      }
      _entries
        ..clear()
        ..addAll(page.entries);
      _hasMore = page.hasMore;
    });
  }

  Future<void> _loadMore() async {
    if (_loadingMore || _entries.isEmpty) return;
    setState(() => _loadingMore = true);
    final page = await HistoryApi.fetch(deviceId: _deviceId, beforeMs: _entries.last.atMs);
    if (!mounted) return;
    setState(() {
      _loadingMore = false;
      if (page != null) {
        _entries.addAll(page.entries);
        _hasMore = page.hasMore;
      }
    });
  }

  void _pickDevice(String? id) {
    if (id == _deviceId) return;
    _deviceId = id;
    _reload();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Scaffold(
      backgroundColor: p.background,
      appBar: AppBar(
        title: const Text('Lịch sử điều khiển'),
        backgroundColor: p.surface,
        actions: [
          IconButton(
            onPressed: _loading ? null : _reload,
            icon: const Icon(Icons.refresh),
            tooltip: 'Tải lại',
          ),
        ],
      ),
      body: Column(
        children: [
          _filters(p),
          Expanded(child: _body(p)),
        ],
      ),
    );
  }

  Widget _filters(AppPalette p) {
    Widget chip(String label, bool selected, VoidCallback onTap) => Padding(
          padding: const EdgeInsets.only(right: 8),
          child: ChoiceChip(
            label: Text(label),
            selected: selected,
            onSelected: (_) => onTap(),
          ),
        );
    return SizedBox(
      height: 52,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        children: [
          chip('Tất cả', _deviceId == null, () => _pickDevice(null)),
          for (final d in _devices)
            chip('${d['name'] ?? d['id']}', _deviceId == '${d['id']}', () => _pickDevice('${d['id']}')),
          Padding(
            padding: const EdgeInsets.only(left: 4),
            child: FilterChip(
              avatar: const Icon(Icons.pan_tool_alt_outlined, size: 16),
              label: const Text('Chỉ ngoài app'),
              selected: _outsideOnly,
              onSelected: (v) => setState(() => _outsideOnly = v),
            ),
          ),
        ],
      ),
    );
  }

  Widget _body(AppPalette p) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) {
      return _Message(
        icon: Icons.cloud_off,
        title: _error!,
        action: TextButton(onPressed: _reload, child: const Text('Thử lại')),
      );
    }
    final shown = _outsideOnly
        ? _entries.where((e) => HistorySource.of(e.source).outside).toList()
        : _entries;
    if (shown.isEmpty) {
      return RefreshIndicator(
        onRefresh: _reload,
        child: ListView(children: const [
          SizedBox(height: 80),
          _Message(
            icon: Icons.history,
            title: 'Chưa có gì',
            subtitle: 'Lệnh điều khiển và thao tác bằng nút trên thiết bị sẽ hiện ở đây.',
          ),
        ]),
      );
    }

    // Phẳng hóa thành [tiêu đề ngày, dòng, dòng, tiêu đề ngày, ...].
    final items = <Object>[];
    DateTime? day;
    for (final e in shown) {
      final d = DateTime(e.at.year, e.at.month, e.at.day);
      if (day != d) {
        day = d;
        items.add(d);
      }
      items.add(e);
    }

    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView.builder(
        padding: const EdgeInsets.only(bottom: 24),
        itemCount: items.length + (_hasMore ? 1 : 0),
        itemBuilder: (context, i) {
          if (i == items.length) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: _loadingMore
                    ? const CircularProgressIndicator()
                    : TextButton(onPressed: _loadMore, child: const Text('Tải thêm')),
              ),
            );
          }
          final it = items[i];
          if (it is DateTime) return _DayHeader(day: it);
          return _EntryTile(entry: it as HistoryEntry);
        },
      ),
    );
  }
}

class _DayHeader extends StatelessWidget {
  final DateTime day;
  const _DayHeader({required this.day});

  static const _weekdays = ['Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7', 'Chủ nhật'];

  String get _label {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final diff = today.difference(day).inDays;
    final date = '${day.day.toString().padLeft(2, '0')}/${day.month.toString().padLeft(2, '0')}';
    if (diff == 0) return 'Hôm nay · $date';
    if (diff == 1) return 'Hôm qua · $date';
    return '${_weekdays[day.weekday - 1]} · $date';
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
      child: Text(
        _label,
        style: TextStyle(color: context.palette.textSub, fontSize: 13, fontWeight: FontWeight.w600),
      ),
    );
  }
}

class _EntryTile extends StatelessWidget {
  final HistoryEntry entry;
  const _EntryTile({required this.entry});

  String _hms(DateTime t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}:${t.second.toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final src = HistorySource.of(entry.source);
    final failed = entry.success == false;
    final accent = failed ? Colors.redAccent : (src.outside ? p.purple : p.primary);
    final viaLabel = entry.userName != null && entry.userName!.isNotEmpty ? ' · ${src.label}' : '';

    return ListTile(
      leading: CircleAvatar(
        backgroundColor: accent.withValues(alpha: 0.15),
        child: Icon(src.icon, color: accent, size: 20),
      ),
      title: Text(
        '${entry.deviceName} · ${entry.actionLabel}',
        style: TextStyle(color: p.textMain, fontWeight: FontWeight.w600),
      ),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('${_hms(entry.at)} · ${entry.actor}$viaLabel', style: TextStyle(color: p.textSub)),
          if (entry.detail != null && entry.detail!.isNotEmpty)
            Text(
              entry.detail!,
              style: TextStyle(color: p.textSub, fontSize: 12),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
        ],
      ),
      trailing: failed
          ? const Tooltip(
              message: 'Thiết bị không nhận lệnh',
              child: Icon(Icons.error_outline, color: Colors.redAccent),
            )
          : null,
      isThreeLine: entry.detail != null && entry.detail!.isNotEmpty,
    );
  }
}

class _Message extends StatelessWidget {
  final IconData icon;
  final String title;
  final String? subtitle;
  final Widget? action;
  const _Message({required this.icon, required this.title, this.subtitle, this.action});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 48, color: p.textSub),
            const SizedBox(height: 12),
            Text(title, textAlign: TextAlign.center, style: TextStyle(color: p.textMain, fontSize: 16)),
            if (subtitle != null) ...[
              const SizedBox(height: 6),
              Text(subtitle!, textAlign: TextAlign.center, style: TextStyle(color: p.textSub)),
            ],
            if (action != null) ...[const SizedBox(height: 8), action!],
          ],
        ),
      ),
    );
  }
}
