# Features — Danh sách chức năng & trạng thái

> Cập nhật qua `/sync-docs`. Mỗi feature có format chuẩn: **Status / Backend / Frontend / Key logic**.

## Format chuẩn

```


### Thành viên: đăng ký tự do, chủ nhà thêm vào nhà · Mật khẩu · Hướng dẫn
- **Status:** ✅
- **Frontend:** `screens/admin_screen.dart` (ô tìm kiếm `foldVietnamese`, nhóm Chưa thuộc nhà / Trong nhà / Đã chặn, nút "Thêm vào nhà" = vai + khu + active trong 1 bước) · `screens/pending_screen.dart` ("Chưa thuộc nhà nào") · `screens/forgot_password_screen.dart` · đổi mật khẩu ở `profile_screen.dart` · `screens/help_screen.dart` + `screens/onboarding_screen.dart`
- **Backend:** không đổi API — "thêm vào nhà" = `PATCH /api/members/{id}` `{status: active, role, zone_ids}`; thông báo 403 pending đổi thành "chưa được thêm vào nhà".
- **Key logic:** đổi mật khẩu bắt nhập mật khẩu HIỆN TẠI (đăng nhập lại) trước `updateUser`; quên mật khẩu = `resetPasswordForEmail` -> `verifyOTP(type: recovery)` -> `updateUser(password)` -> đã đăng nhập. Mã dài 6-10 số (Supabase cho chỉnh độ dài).

### Kịch bản (scenes) + khu dùng chung + nhà theo khu
- **Status:** ✅ (nhánh release/prod-ready, chưa lên production)
- **Backend:** `models/scene.py` · `/api/scenes` (+ `/run`) · `zones.is_shared` · `core/household._visible_zone_ids` (khu được cấp HOẶC dùng chung — 1 subquery cho device/zone/schedule query) · `require_scene_write`
- **Frontend:** `core/scene_api.dart` · `screens/scene_editor_screen.dart` · hàng kịch bản + chip lọc khu trên `dashboard_tab.dart` · `core/zone_groups.dart` · admin menu khu "Dùng chung cả nhà"
- **Key logic:**
  - Hành động kịch bản CHUẨN HÓA lúc lưu qua `normalize_action` (sai loại → 400). Chạy TUẦN TỰ (tránh lệnh chen làm lẫn interlock cửa). Thiết bị ngoài khu người chạy → bỏ qua, báo `skipped`.
  - Kịch bản có MỞ CỬA: app hỏi xác nhận (`sceneOpensDoor`); gọi bằng giọng nói → TỪ CHỐI (nhận dạng có thể nghe nhầm).
  - Giọng nói: `local_parser.match_scene` — tên kịch bản xuất hiện trong câu (tên dài nhất thắng), xét TRƯỚC tường lửa từ khóa thiết bị; câu có giờ hẹn thì không khớp.
  - Chip "Phòng khách 1/3": thứ tự khu theo backend (sort_order), kéo-thả thiết bị chỉ ở "Tất cả". Ô thống kê dùng số thật (thiết bị/đang bật/khu) — trước đây "24°C / 60%" viết cứng.

### Giao diện sáng/tối + Hồ sơ cá nhân + đọc phản hồi
- **Status:** ✅
- **Backend:** `members.avatar_color` · `PATCH /api/me` (chỉ tên + màu của chính mình)
- **Frontend:** `theme/app_colors.dart` (`AppPalette`) · `core/theme_controller.dart` · `screens/profile_screen.dart` · `core/avatar.dart` · `core/voice_feedback.dart` (flutter_tts)
- **Key logic:** bản tối giữ NGUYÊN màu cũ; bản sáng màu nhấn đậm hơn cho đủ tương phản. Mặc định Tối. Icon status bar đổi theo nền (`AnnotatedRegion`). TTS dừng khi bật mic (tránh mic thu lại giọng đọc); speech_to_text `initialize` 1 lần, mic bị từ chối → giải thích + nút Mở Cài đặt.

### <Tên feature>
- **Status:** 📋 planned | 🚧 in progress | ✅ done
- **Backend:** model · service · endpoints liên quan
- **Frontend:** core · screens · widgets · native
- **Key logic:** điểm logic quan trọng/dễ sai
```

---

## Features

### Hẹn giờ thiết bị (schedule server-side: đơn + khoảng)
- **Status:** ✅ done
- **Backend:** `ScheduleModel` (`models/schedule.py`, bảng `schedules`) · `services/scheduler.py` (`scheduler_loop` + `execute_schedule_action` + `_is_time_due`/`_end_days`) · `run_startup_migrations` (`core/database.py`) · `/api/schedules` GET/POST/PATCH/DELETE + `/api/schedules/{id}/run?part=start|end` + helper `_create_schedule_row` (`main.py`) · test `backend/tests/test_scheduler_helpers.py`.
- **Frontend:** `core/schedule_api.dart` (`Schedule` model + `ScheduleApi`) · `screens/schedule_tab.dart` (tab thứ 3 "Hẹn giờ": list + form bottom-sheet) · `main.dart` (NavigationDestination + IndexedStack).
- **Key logic:**
  - **Hẹn giờ ĐƠN**: 1 lịch = 1 thiết bị + 1 giờ (`"HH:MM"` giờ VN) + 1 hành động (`on`/`off`/`mode`+value) + ngày lặp (`days` CSV 0=Thứ2…6=CN, rỗng = mỗi ngày).
  - **Hẹn giờ KHOẢNG**: thêm `end_time` + `end_action_type/value` — 2 mốc trong 1 lịch (vd 16:30 lọc Cao → 17:30 lọc TB). `end_time` NULL = lịch đơn (backward compatible). **Qua đêm**: `end_time < time` hợp lệ, end kích hoạt NGÀY HÔM SAU — ngày check end dịch +1 mod 7 (`_end_days`); chỉ chặn end == start. Start và end bắn ĐỘC LẬP, mỗi mốc có fired-date riêng (`last_fired_date`/`last_end_fired_date`) → restart giữa khoảng vẫn trả thiết bị về trạng thái "sau".
  - **One-shot** (`one_shot=True`): lịch đơn tự `enabled=False` sau start; lịch khoảng tắt sau end. Lỡ trọn cửa sổ của hành động cuối (server ngủ) → tự tắt + log "lịch 1 lần đã lỡ giờ" (tránh bắn nhầm tuần sau cùng thứ). Dùng cho lịch tạo từ giọng nói.
  - Cột mới thêm bằng `run_startup_migrations(engine)`, gọi cùng `create_all` trong `init_db()` (`main.py`) — ALTER TABLE cột thiếu, idempotent (create_all KHÔNG alter bảng đã tồn tại). `init_db()` chạy **trong lifespan** bọc try/except (không phải tầng import): lỗi DB → boot degraded, không sập app.
  - Vòng lặp asyncio khởi động trong **lifespan** (`main.py`) — **chỉ khi `db_ready=True`**, tick **30s**: mốc "đến giờ" khi `0 <= now - giờ hẹn < 120s` (grace) VÀ fired-date != hôm nay. **Đánh dấu fired-date TRƯỚC khi gửi lệnh** → lệnh chậm/lỗi không bắn lặp (an toàn với motor cửa). Lỗi 1 lịch không dừng vòng lặp; start xử lý trước end trong cùng tick (khoảng ngắn hơn grace vẫn đúng thứ tự).
  - Hành động tái dùng nguyên primitive connector (`turn_on`/`turn_off`/`set_mode`) + `_cache_invalidate` sau lệnh (truyền callback từ main.py, tránh circular import).
  - PATCH đổi `time`/bật `enabled` → reset `last_fired_date`; đổi `end_time`/bật enabled → reset `last_end_fired_date`; gửi `end_time: null` TƯỜNG MINH → xóa sạch bộ end (thành lịch đơn). Validate merged (giá trị mới ưu tiên, thiếu lấy từ row): action ∈ on/off/mode, mode cần value (cùng luật cho bộ end), time regex HH:MM, days CSV 0-6, có end_time thì bắt buộc end_action_type.
  - `/run` chạy ngay để test (KHÔNG đổi fired-date); `?part=end` chạy hành động kết thúc (lỗi rõ nếu lịch đơn).
  - Múi giờ cố định `ZoneInfo("Asia/Ho_Chi_Minh")` (server Render chạy UTC) — cần `tzdata` trong requirements.
  - ⚠️ Phụ thuộc server luôn thức (UptimeRobot ping `/health`); ổ đĩa Render free ephemeral → lịch mất khi **redeploy** (nâng cấp DB ngoài nếu cần bền).
  - Form frontend: `SegmentedButton` "Một mốc"/"Khoảng"; Khoảng hiện thêm tile Giờ kết thúc + chip Hành động kết thúc (đổi thiết bị reset cả 2 action key); end == start chặn bằng snackbar, end < start hiện ghi chú "Kết thúc vào ngày hôm sau (lịch qua đêm)". Card khoảng hiện `"16:30 → 17:30"` (fontSize 18, qua đêm thêm `⁺¹`) + `"Lọc Cao → Lọc TB • <tên>"` (`_actionSummary`); tag "1 lần" khi `oneShot`. Hành động theo **loại thiết bị** (`device_type.dart`): máy lọc = Bật/Tắt/Thấp/TB/Cao/Auto/Ngủ; cửa = Mở/Đóng; máy ăn = Nhả 1-3 phần. Tap card để sửa; Switch bật/tắt lịch (PATCH); nút xóa có dialog xác nhận.

### Quản lý thiết bị (devices)
- **Status:** ✅ done
- **Backend:** `DeviceModel` (`models/device.py`) · `/api/devices` GET/POST/DELETE (`main.py:118-155`).
- **Frontend:** `device_api.dart` (`fetchDevices`/`fetchStatus`/`sendMode`/`sendAction`) · `dashboard_tab.dart` (list + card).
- **Key logic:** loại thiết bị phân ở client qua `core/device_type.dart` (**nơi duy nhất**): `deviceTypeOf(name, category:)` — `category` từ backend (`purifier`/`curtain`/`feeder`/`switch`) thắng, NULL/lạ → suy từ TÊN ('bơm'/'tăng áp'/'công tắc'→powerSwitch — kiểm TRƯỚC vì "tăng áp" chứa "ăn"; 'lọc'→airPurifier, 'cửa'→curtain, 'mèo'/'ăn'→feeder). Card powerSwitch: switch bật/tắt + nhãn Đang chạy/Đã tắt/Mất kết nối, poll 6s như máy lọc — dùng chung bởi dashboard, widget_service, schedule_tab. Card máy lọc & cửa có nhãn trạng thái sống (`statusLabel`) đọc từ `/status`. Base URL/timeout gom về `core/config.dart` (`AppConfig`).

### Điều khiển bật/tắt & chế độ
- **Status:** ✅ done
- **Backend:** `/api/test-control/{brand}/{id}?action=` và `/mode?mode=` (`main.py`) → connector `turn_on/turn_off/set_mode`.
- **Frontend:** `DeviceApi.sendMode`/`sendAction` · nút mode + switch trong `dashboard_tab.dart`.
- **Key logic:**
  - Endpoint kiểm tra `bool` connector trả về — lệnh thất bại → `{status:"error"}` (không còn luôn "success"). `DeviceApi._isOk` đọc `body['status']` chứ không chỉ HTTP 200.
  - Frontend: `_sending` chặn double-tap; `_pendingMode` tô sáng lạc quan nút vừa bấm. **Reconcile theo giá trị**: `_refreshStatus` chỉ xóa `_pendingMode` khi `_currentModeValue(status thật)` KHỚP mode vừa bấm (hoặc quá hạn `_pendingSince` ~10s) → highlight KHÔNG nhảy về mode cũ khi cloud chưa propagate. `_refreshAfterCommand` poll lại nhiều nhịp (~0.7/1.3/2/3s) với `fresh=true` (bỏ cache), dừng sớm khi đã khớp.
  - Nút cửa (Mở/Dừng/Đóng) KHÔNG bị khóa — luôn bấm được; tô sáng nút khớp `door_state` (`activeDoorMode`). Backend tự chèn `stop` trước open/close nên an toàn.
  - Connector Tuya/Rojeco dùng `asyncio.to_thread` cho call HTTP đồng bộ → không block event loop. Mode phụ thuộc brand (tuya: open/close/stop; vesync: low/med/high/auto/sleep/off).

### Trạng thái sống thiết bị
- **Status:** ✅ done
- **Backend:** `/api/devices/{brand}/{id}/status` (`main.py`, opt `?fresh=1` bỏ cache) → `connector.get_device_state`; cache in-memory TTL ~3s (`_status_cache`), tự xóa sau mỗi lệnh điều khiển.
- **Frontend:** `DeviceApi.fetchStatus(brand, id, {fresh})` (`device_api.dart`) — dùng ở dashboard & shortcut handler; card máy lọc/cửa tự động poll `Timer.periodic(6s)` (dùng cache), refresh sau lệnh dùng `fresh:true`. **Poll tự tạm dừng** khi tab Home ẩn (`DashboardTab.isVisible` từ IndexedStack) hoặc app vào nền (`WidgetsBindingObserver`), refresh ngay khi hiển thị lại (`didUpdateWidget` + `_setPolling`). Card báo ON/OFF thật về parent qua `onStatusChanged` → header đếm "Đang bật" chính xác (trước đây chỉ đếm `is_active` tĩnh).
- **Key logic:** shape khác nhau theo brand; field chung là `status` (ON/OFF/offline). Tuya thêm `door_state`/`position`; VeSync thêm `mode`/`speed`. Rojeco: `status` ON(online)/offline + `feed_state` (standby/feeding/done) + `last_feed` (DP `feed_report`); card + widget hiện "Sẵn sàng • lần trước N phần" / "Đang nhả hạt..." / "Mất kết nối".
  - VeSync connector viết cho pyvesync 3.4.2: `_read()` ưu tiên `purifier.state.*` (tránh property deprecated), bọc try/except. `set_mode` ưu tiên API mới `set_fan_speed`/`set_auto_mode`/`set_sleep_mode` (fallback hàm cũ), validate theo `purifier.fan_levels`.
  - **Tuya cửa — suy `door_state` từ trạng thái THẬT trên cloud, KHÔNG từ lịch sử lệnh app.** `get_device_state` đọc DP status từ cloud rồi ưu tiên theo thứ tự: (1) **vị trí thật** (thử lần lượt `_POSITION_DPS`=`percent_state`/`position`/`curtain_position`/`percent_control`) → 100=open, 0=closed, giữa=partial; (2) **tình trạng thật** (`_WORK_STATE_DPS`=`work_state`/`doorcontrol_state`/`situation_set`/`door_state`) map qua `_WORK_STATE_MAP`; (3) **chỉ khi không có (1)(2)** mới fallback DP `control` (= LỆNH CUỐI echo trên cloud, có thể cũ/kẹt). Không nhận ra DP nào → `unknown` + in cảnh báo `[Tuya Door] ⚠️ ... dps=...`. Tên DP là danh sách ứng viên (hằng số đầu `tuya_connector.py`) — bổ sung tên nếu log báo thiết bị dùng tên khác.

### Trợ lý giọng nói (AI)
- **Status:** ✅ done
- **Backend:** `/api/ai/parse` (`main.py`) — firewall từ khóa thiết bị → local parser (câu đơn) hoặc AI (câu phức có "và/rồi/với/nhưng") → thực thi song song `asyncio.gather`.
- **Frontend:** `ai_assistant_tab.dart` (speech-to-text) · `chat_bubble.dart` · `websocket_provider.dart`.
- **Key logic:**
  - Câu không chứa từ khóa thiết bị bị chặn sớm (không gọi AI); firewall có thêm "hẹn"/"lịch" cho câu hẹn giờ. Local parser ưu tiên để tiết kiệm chi phí LLM.
  - **Executor nhận cả 2 bộ giá trị action**: AI phát `on`/`off`, local parser phát `turn_on`/`turn_off` — dispatch trong `execute_single_action` khớp cả hai (fix lỗi lệnh local "bật/tắt máy lọc" không chạy). Sau mỗi action gọi `_cache_invalidate` (như endpoint control) để status đọc lại không dính cache cũ.
  - `ai_parser.py`: client OpenRouter khởi tạo **lười** (`_get_client`) — thiếu `OPENROUTER_API_KEY` app vẫn boot, chỉ AI fallback bị vô hiệu (trả `[]` + log warning).
  - Frontend: request có timeout 30s; non-200 hiện bubble lỗi (trước đây `_isTyping` kẹt vô hạn); `dispose()` giải phóng controller/timer/mic. WebSocket tự connect khi vào tab, dùng `AppConfig.wsUrl` (wss Render), báo "Live" chỉ sau `channel.ready`, giữ tối đa 200 message.

### Giọng nói TẠO lịch hẹn (NL → schedule)
- **Status:** ✅ done
- **Backend:** `services/vn_time_parser.py` (MỚI: `extract_schedule_times` + `resolve_target_days`) · `local_parser.py` (intent schedule, refactor `_extract_device_actions`) · `main.py` (`_create_schedule_from_intent`, `_verb_to_schedule_action`, `_action_label_vn`) · prompt few-shot schedule trong `ai_parser.py` · test `backend/tests/test_vn_time_parser.py`.
- **Frontend:** không cần sửa — bubble "Đã hẹn 16:30 • Chế độ 3" render bằng `chat_bubble.dart` sẵn có; lịch mới hiện trong tab Hẹn giờ sau refresh.
- **Key logic:**
  - **Trigger = parse được mốc giờ.** `parse_command_locally` gọi `extract_schedule_times(text)` TRƯỚC: None → đường thi hành ngay như cũ (hành vi không đổi); có giờ → CHỈ trả `{"intent":"schedule", brand, id, action, mode, time, end_time, end_action, end_mode, day_offset, recurring_daily}` hoặc `[]` (AI fallback thử). KHÔNG BAO GIỜ trộn schedule + immediate → "hẹn 16h30 bật quạt" không thể bật quạt luôn.
  - `vn_time_parser` nhận: "16 giờ 30"/"16h30"/"16:30"/"X giờ rưỡi"/"X giờ Y phút", giờ chữ 1-12 ("bảy giờ"), buổi sáng/trưa/chiều/tối/đêm (cửa sổ quanh mốc, loại trừ "tối đa"; khoảng thiếu buổi 1 bên → chia sẻ buổi nếu giữ được end > start), "mai"→day_offset 1, "mỗi ngày/hàng ngày"→recurring, "từ X đến/tới Y"→khoảng (end < start = qua đêm). Trả kèm `cleaned_text/head/tail` (đã cắt cụm giờ/buổi — tránh "đêm" trong "11 giờ đêm" match nhầm mode sleep).
  - Trích thiết bị/hành động chạy trên `cleaned_text` (tái dùng nguyên keyword matching cũ). Khoảng 2 hành động: parse riêng head/tail quanh mốc "đến" (tail thiếu từ khóa thiết bị → ghép mồi `_BRAND_HINT`); khoảng 1 hành động → end mặc định Tắt, cửa mở→đóng, cửa đóng/dừng KHÔNG đoán (an toàn: không tự mở cửa → rơi về lịch đơn).
  - `_create_schedule_from_intent` (main.py): map verb parser (`turn_on/turn_off/set_mode` | `on/off`) → cột lịch (`on/off/mode`), `resolve_target_days` ghim thứ ngày đích + `one_shot=True` (recurring → days rỗng, không one-shot; giờ đã qua hôm nay → tự roll sang mai), tạo row qua `_create_schedule_row` dùng chung với POST endpoint, KHÔNG chạm connector/cache. Lỗi validate → bubble "Lỗi hẹn giờ: ..." success=False.
  - AI fallback (câu phức): prompt `ai_parser.py` rule 4 + 3 few-shot schedule, output shape GIỐNG HỆT local parser → cùng đi qua `_create_schedule_from_intent`; thời gian AI trả bị re-validate server-side (regex) nên garbage không crash.

### Sắp xếp thứ tự thiết bị (kéo-thả)
- **Status:** ✅ done
- **Backend:** không đổi (thứ tự là tuỳ biến hiển thị phía client; `DeviceModel` không có cột thứ tự).
- **Frontend:** `core/device_order.dart` (lưu/áp thứ tự qua `shared_preferences`) · `dashboard_tab.dart` (`SliverReorderableList` + `ReorderableDelayedDragStartListener`).
- **Key logic:**
  - Kéo bằng **tay cầm riêng** (`dragHandle` = `ReorderableDragStartListener` bọc icon `drag_indicator` ở cuối header thẻ), KHÔNG bọc cả thẻ. ⚠️ Bọc cả thẻ bằng `ReorderableDelayedDragStartListener` gây **xung đột cử chỉ** với nút/switch bên trong → nhấn giữ trúng nút hiện message lỗi; tay cầm riêng loại bỏ xung đột này.
  - `_onReorder` dùng `onReorderItem` (newIndex ĐÃ điều chỉnh cho item bị gỡ) → `removeAt`/`insert` rồi `DeviceOrder.save([ids])`. `proxyDecorator` bọc thẻ đang kéo trong `Material` (bo góc + đổ bóng).
  - `fetchDevices` gọi `DeviceOrder.apply(devices, order)`: sắp theo thứ tự đã lưu; thiết bị CHƯA có trong thứ tự (mới thêm) giữ thứ tự backend và đẩy xuống cuối.
  - Lưu CỤC BỘ (`SharedPreferences` key `device_order_v1`) → thứ tự riêng từng máy, không đồng bộ cloud. Card bỏ animation entrance để tránh nhấp nháy khi kéo; key `ValueKey(id)` giữ state card (poll không restart) khi đổi chỗ. Gợi ý "Kéo biểu tượng ⋮⋮ bên phải thẻ để sắp xếp" hiện khi có >1 thiết bị.

### Home-screen Shortcut (icon xử lý nhanh)
- **Status:** ✅ done
- **Backend:** dùng lại `/status` + `/mode`.
- **Frontend:** `shortcut_service.dart` (MethodChannel `smarthome/shortcuts`, quick_actions iOS) · `shortcut_handler.dart` (handle + `ShortcutIcons`) · `MainActivity.kt` (buildShortcut/resolveIcon/pin/update) · `res/drawable/ic_*`.
- **Key logic:**
  - Icon phản ánh trạng thái: `ShortcutIcons.purifier/door/feeder` map trạng thái → tên drawable; native `resolveIcon()` tra theo tên trong `drawable`/`mipmap`, thiếu → fallback `launcher_icon`. **Các drawable ic_purifier_*/ic_door_*/ic_feeder phải tồn tại** (đã tạo).
  - Khi bấm: purifier/door đọc trạng thái thật (`fetchStatus`) → tính bước kế → thực thi → `updateShortcutIcon` cho khớp; feeder/door open/close chỉ hỏi xác nhận. Cửa: sau `sendMode` set icon lạc quan theo mục tiêu rồi `_reconcileDoorIcon` poll lại `fresh` (~2s) chỉnh icon theo `door_state` THẬT (bắt kịp cả khi lệnh không đạt như ý).
  - **Icon hội tụ theo trạng thái THẬT khi app mở:** `dashboard_tab._syncShortcutIcon` gọi trong vòng poll 6s (`_refreshStatus`) — mỗi lần đọc được trạng thái thật, đẩy `updateShortcutIcon` cho cửa/quạt cho khớp → icon đúng cả khi thiết bị bị điều khiển từ remote vật lý / app khác. Gọi `updateShortcut` cho id chưa pin là **no-op an toàn** (native `ShortcutManagerCompat.updateShortcuts` chỉ ảnh hưởng shortcut đang tồn tại) nên không cần lưu danh sách pinned; có `_lastShortcutIcon` chặn gọi native lặp khi icon không đổi.
  - ⚠️ Giới hạn: pinned shortcut là ảnh tĩnh, không badge/text sống; chỉ cập nhật được **khi app đang chạy** (poll dashboard / lúc bấm). App đóng hoàn toàn + điều khiển bằng remote vật lý → icon vẫn cũ tới lần app mở/poll kế. Một số launcher cache icon pinned. iOS quick action vẫn dùng logo app.

### Home Screen Widget (App Widget)
- **Status:** ✅ done
- **Backend:** dùng lại `/api/devices`, `/status`, `/mode`, `/test-control`.
- **Frontend:** `core/widget_service.dart` (đẩy dữ liệu + callback nền) · `DeviceApi.fetchDevices` · `SmartHomeWidgetProvider.kt` · `res/layout/smart_home_widget.xml` · `res/xml/smart_home_widget_info.xml` · package `home_widget` · đăng ký receiver/service trong `AndroidManifest.xml`.
- **Key logic:**
  - 3 khe cố định theo loại (`deviceTypeOf` — category trước, rồi tên): p=máy lọc, c=cửa, f=máy cho ăn. Khe không có thiết bị → ẩn (`{slot}_visible`).
  - Dữ liệu đẩy qua `HomeWidget.saveWidgetData` (string), vẽ lại bằng `updateWidget(qualifiedAndroidName: com.example.frontend.SmartHomeWidgetProvider)`.
  - Nút bấm → `HomeWidgetBackgroundIntent` (URI `smarthome://action?type&brand&id` hoặc `smarthome://refresh`) → `widgetBackgroundCallback` (@pragma vm:entry-point) chạy NỀN, gọi DeviceApi rồi `refreshAll()` cập nhật lại. KHÔNG mở app.
  - App đang mở: `dashboard_tab.fetchDevices` thành công → `WidgetService.refreshAll()` đồng bộ widget.
  - App ĐÓNG: `WidgetRefreshWorker` (WorkManager, 15 phút, cần mạng) bắn `smarthome://refresh` → `refreshAll()` ở isolate nền (chỉ đọc). Trước đây widget chỉ cập nhật khi mở app/bấm ↻.
  - ⚠️ Giới hạn: chỉ hiện 1 thiết bị/loại (nếu có 2 máy lọc chỉ hiện 1). Trạng thái phụ thuộc backend (Render free có thể ngủ → "Không rõ").

### Automation engine
- **Status:** 📋 planned (đóng băng)
- **Backend:** `automation_engine.py` — không được import trong `main.py`.
- **Key logic:** chưa kích hoạt; tính năng Hẹn giờ dùng `services/scheduler.py` riêng (persist DB) thay vì engine này (rule in-memory).

### Đăng nhập (Supabase Auth) + AuthGate
- **Status:** 🚧 code xong, chưa bật production (chờ tạo project Supabase và build APK kèm khóa)
- **Backend:** `core/auth.py` (`issue_app_token`, chấp nhận app-token trong `get_current_user`; `_decode_supabase_token` verify ES256 qua JWKS của `SUPABASE_URL` hoặc HS256 qua `SUPABASE_JWT_SECRET`) · `POST /api/auth/app-token`
- **⚠️ Project Supabase của nhà ký token bằng ES256** (Settings → JWT Keys). App dùng **Publishable key** `sb_publishable_...` (thay "anon key" cũ) cho `--dart-define=SUPABASE_ANON_KEY`.
- **Frontend:** `core/auth_service.dart` · `screens/auth_gate.dart` · `screens/login_screen.dart` · `screens/pending_screen.dart` (+ `OfflineScreen`) · header gắn ở `device_api`/`schedule_api`/`ai_assistant_tab`/`dashboard_tab` · `main.dart` init Supabase trước `runApp` · test `test/auth_service_test.dart`, `test/widget_test.dart`
- **Key logic:**
  - **⚠️ Isolate nền là đường hỏng ÂM THẦM của phase này.** `widgetBackgroundCallback` (`@pragma('vm:entry-point')`) và shortcut handler chạy ở **isolate riêng**, nơi `Supabase.instance` chưa từng được khởi tạo ⇒ không lấy được access token ⇒ Home Widget hiện "Không rõ" và nút bấm **không làm gì, không báo lỗi, không crash**. Ba cách sai đã loại: (a) init Supabase trong isolate → hai isolate refresh song song, mà Supabase **xoay vòng refresh token** ⇒ isolate này vô hiệu hóa token của isolate kia, cả nhà bị đăng xuất ngẫu nhiên; (b) cache access token 1 giờ → hỏng mỗi khi bấm widget sau 1 giờ, tức hầu như luôn; (c) bỏ qua → mất 2 tính năng đầu bảng. **Giải:** `POST /api/auth/app-token` cấp JWT dài hạn do backend ký (`iss="smarthome-app"`), lưu SharedPreferences — đọc được ở mọi isolate. Thu hồi = đổi `APP_TOKEN_SECRET`.
  - `accessToken()` thử Supabase trước (tự refresh khi hết hạn), rồi rơi xuống app-token. Cờ `_supabaseReady` là static của isolate nên ở isolate nền nó false và Supabase bị bỏ qua thay vì ném lỗi.
  - **`headers()` NÉM `NotAuthenticatedException`** thay vì im lặng bỏ header. Hành vi cũ khiến server trả 401 và UI báo "Mất kết nối máy chủ" — sai chẩn đoán, sai cách phục hồi.
  - **`AuthGate` 5 trạng thái** `loading | signedOut | pending | offline | ready`. `loading` tồn tại vì thiếu nó thì cold start **nháy màn đăng nhập** trong lúc session đã lưu chưa resolve xong. `offline` tồn tại vì rớt mạng **khác** hết phiên — đăng xuất người dùng chỉ vì Render đang ngủ là bắt gõ lại mật khẩu vô cớ. `dispose()` cancel `StreamSubscription` (thiếu là setState trên widget đã chết).
  - **401 ≠ 403.** 401 = phiên chết → đăng xuất. 403 = "chờ chủ nhà duyệt" hoặc "ngoài khu được cấp" → hiện thông báo, **không** đăng xuất.
  - **Chuyển tiếp an toàn:** `AppConfig.authEnabled` false khi chưa truyền `--dart-define=SUPABASE_URL/SUPABASE_ANON_KEY` ⇒ AuthGate vào thẳng app với `HouseholdProfile.openHouse`, khớp backend đang để xác thực TẮT. Không có nhánh này thì bản build thiếu khóa **kẹt ở màn login vĩnh viễn**.
  - **Mọi call site đều phải có header.** `dashboard_tab.fetchDevices` trước đây gọi `http.get` thẳng — call site duy nhất thiếu token; bật xác thực lên là dashboard trống trơn trong khi mọi thứ khác vẫn chạy. Nay đi qua `DeviceApi`.
  - anon key nằm trong APK nên **không phải bí mật**; an toàn đến từ RLS deny-all trên mọi bảng.
  - Giữ luồng **đăng ký** ở `login_screen`: ăn khớp cơ chế chờ-duyệt ở backend. Bỏ nó thì chủ nhà phải tự tạo tài khoản và đặt lại mật khẩu cho từng người trong dashboard Supabase.

### Khu vực + thành viên + phân quyền theo khu
- **Status:** 🚧 backend xong, chưa có UI (Phase 2-3 mới làm màn hình đăng nhập/quản trị)
- **Backend:** `core/household.py` · `core/auth.py` · `models/member.py`, `models/zone.py` · `devices.zone_id`, `schedules.created_by` · `main.py` `/api/me`, `/api/zones`, `/api/members`, `PATCH /api/devices/{id}` + rescope toàn bộ endpoint cũ · test `tests/test_household_scope.py`
- **Frontend:** `core/household_api.dart` (Zone/Member model + CRUD) · `screens/admin_screen.dart` (2 tab) · lối vào ở menu tài khoản trên `dashboard_tab.dart`, chỉ hiện khi `can_admin` · test `test/admin_screen_test.dart`
- **Key logic:**
  - **Mô hình:** thiết bị thuộc **khu vực**, thành viên được cấp quyền theo **khu**. Không phải `devices.user_id` sở hữu phẳng — mô hình đó không chia sẻ được thiết bị, mà cả nhà vốn dùng chung cửa cuốn và máy lọc khí.
  - **Không có bảng `homes`.** Một cột luôn bằng 1 trên mọi bảng là trả giá ngay để dùng sau nhiều năm. Điều làm "nhiều nhà" rẻ về sau là dồn hết scoping vào `core/household.py`: lúc cần chỉ thêm cột `home_id` + sửa 2 hàm, không đụng endpoint nào.
  - **Ma trận quyền** (một cơ chế duy nhất): `owner` quản trị được tất cả · `adult` thấy mọi khu, không quản trị · `kid` chỉ khu được cấp, tạo được lịch, chỉ sửa lịch của chính mình · `guest` chỉ khu được cấp, không tạo lịch · `pending`/`blocked` bị 403 mọi nơi trừ `/api/me`.
  - **Cấp theo KHU chứ không theo từng thiết bị:** per-device là O(thành viên × thiết bị) hàng phải bảo trì mỗi lần mua thêm ổ cắm; per-zone thì thiết bị mới **thừa hưởng** quyền từ phòng.
  - **`zone_id IS NULL` = "hộp thư đến"**: thiết bị vừa import chưa gán phòng, chỉ owner/adult thấy. Rơi ra **miễn phí** từ `INNER JOIN` trong `device_query` — không có case đặc biệt nào.
  - **403 chứ không 404** khi thiết bị có trong nhà nhưng ngoài khu của mình — trong nhà không cần giấu nhau việc thiết bị đó tồn tại.
  - Vai và grant đọc từ DB **mỗi request** ⇒ duyệt / đổi vai / chặn có hiệu lực ngay ở request kế tiếp, không bắt đăng nhập lại (khác hẳn nhét role vào JWT).
  - Quyền **không bao giờ xuất hiện trong thân endpoint** — endpoint chỉ gọi `device_query` / `require_device_access` / `require_owner` / `require_schedule_write`.
  - **Người lạ đăng nhập lần đầu** → `guest`/`pending`, 0 grant: đăng nhập được, `/api/me` được, mọi thứ khác 403 "Đang chờ chủ nhà phê duyệt". Email trong `ADMIN_EMAILS` **luôn** được nâng lên `owner`/`active`, kể cả khi hàng trong DB đã bị hạ vai — cứu hộ để chủ nhà không tự khóa mình khỏi nhà mình.
  - **Lịch hẹn là của CẢ NHÀ**: `schedule_query` lọc theo THIẾT BỊ (ai thấy thiết bị thì thấy lịch của nó), không theo `created_by`. Cột `created_by` chỉ dùng để chặn kid sửa lịch bố mẹ đặt.
  - **Chặn tự khóa mình ở tầng API** (không chỉ UI — app bản cũ hoặc request gõ tay vẫn đi thẳng vào): không tự hạ vai, không tự chặn mình, không hạ vai/chặn `owner` cuối cùng.
  - **Hai bug sẵn có sửa cùng lúc:** `DELETE /api/devices/{id}` giờ xóa luôn lịch của thiết bị (trước đây lịch mồ côi vẫn được scheduler bắn vào thiết bị không tồn tại, mỗi ngày, mãi mãi); `POST /api/devices` idempotent (id trùng = "đã có trong nhà").
  - **UI quản trị (Phase 3):** tab **Thành viên** ghim người chờ duyệt lên đầu — đó là việc cần làm, không phải danh sách để cuộn tìm; **ẩn ô tick khu với owner/adult** vì hai vai này thấy mọi khu theo luật vai, tick vào chẳng đổi gì mà lại khiến chủ nhà tưởng mình cấp thiếu. Tab **Khu vực** ghim pseudo-zone "Chưa phân khu" ở CUỐI và mặc định mở: thiết bị mới import rơi vào `zone_id NULL`, không hiện ở đâu thì chủ nhà không biết chúng tồn tại.
  - **Menu tài khoản LUÔN hiện**, kể cả khi chưa bật đăng nhập: chủ nhà cần vào Quản trị **chia phòng trước** rồi mới bật xác thực — ngược lại thì lúc duyệt trẻ em không có khu nào để cấp.
  - Chốt *"không hạ vai chủ nhà cuối cùng"* trong `update_member` hiện **không chạm tới được**: người thao tác bắt buộc đã là owner/active nên hạ vai owner khác thì luôn còn ≥2 owner, còn tự hạ vai đã bị chốt "chính mình" bắt trước. Giữ làm backstop; test ghim **bất biến** "nhà không bao giờ mất chủ" chứ không ghim nhánh code đó.
  - ⚠️ **Xác thực TỰ SUY** — xem section "Cấu hình & bảo mật (env)".

### Lưu dữ liệu bền (Postgres/Supabase)
- **Status:** 🚧 code xong, chưa bật trên production (chờ đặt `DATABASE_URL` trên Render — bước 4 của `backend/docs/SUPABASE_SETUP.md`)
- **Backend:** `core/database.py` · `docs/supabase_schema.sql` · `docs/SUPABASE_SETUP.md` · `tests/test_database_schema.py`
- **Frontend:** không đổi gì — app không cần build lại.
- **Key logic:**
  - **Vấn đề:** ổ đĩa Render free là ephemeral; container dựng lại mỗi lần deploy nên `backend/smarthome.db` (đang bị track trong git) bị ghi đè bằng bản chụp trong repo ⇒ **mọi lịch hẹn người dùng tạo đều mất sau mỗi lần deploy**. Postgres nằm ngoài container nên không bị.
  - `DATABASE_URL` quyết định DB. Không đặt → fallback SQLite y như cũ (dev offline không đổi gì). `normalize_database_url` đổi `postgres://` → `postgresql://` (SQLAlchemy 2.x chỉ nhận dạng sau; thiếu bước này thì lỗi mơ hồ `NoSuchModuleError`).
  - `normalize_database_url` / `make_engine` tách thành hàm thuần để test được **mà không phải reload module** — reload tạo `Base` mới, models đã nằm trong `sys.modules` nên không đăng ký lại ⇒ `create_all` không tạo gì.
  - Pool Postgres: `pool_pre_ping` (Render ngủ → kết nối chết) + `pool_recycle=1800` (Supabase pooler cắt kết nối cũ).
  - `init_db()` theo thứ tự: `create_all` → `run_startup_migrations` → `verify_schema` → `enable_rls` → `seed_defaults`. **verify phải TRƯỚC seed**: ngược lại thì schema lệch làm seed ném `OperationalError` thô, che mất thông báo nói rõ thiếu cột nào.
  - `run_startup_migrations` chạy cho **cả hai dialect**; DDL tách riêng vì Boolean của SQLite là `INTEGER` còn Postgres là `BOOLEAN` — dùng chung một DDL sẽ lỗi trên Postgres.
  - `verify_schema()` raise kèm tên bảng/cột thiếu → `lifespan` bắt → boot degraded, `/health` trả `db:false`. Không có nó thì schema lệch chỉ lộ ra ở request 500 đầu tiên.
  - `enable_rls()` bật RLS trên Postgres nhưng **không viết policy**: Supabase grant sẵn quyền cho role `anon`/`authenticated` mà anon key nằm ngay trong APK; bật RLS không policy = deny-all, còn backend nối bằng role `postgres` nên bỏ qua RLS và vẫn chạy.
  - `seed_defaults()` nạp 3 thiết bị nếu bảng `devices` rỗng, **giữ NGUYÊN id** (shortcut đã pin và slot Home Widget lưu theo `brand`+`id`, đổi id là hỏng cả hai mà không báo lỗi). Chỉ chạy khi rỗng ⇒ không ghi đè tên người dùng đã sửa hay thiết bị đã xóa.
  - ⚠️ Bẫy kết nối: phải dùng chuỗi **Session pooler** của Supabase (IPv4, port 5432). Direct connection chỉ có IPv6 mà Render free không hỗ trợ → `Network is unreachable`.
  - Phase 1a **chỉ đổi chỗ lưu**. Chưa có đăng nhập, chưa có phân quyền, chưa có bảng thành viên/khu vực.

### Cấu hình & bảo mật (env)
- **Status:** ✅ done
- **Backend:** `load_dotenv()` đầu `main.py` · `backend/.env` (thật, gitignore) · `backend/.env.example` (mẫu).
- **Key logic:** `VESYNC_EMAIL/PASSWORD` (main.py), `TUYA_ACCESS_ID/KEY/API_ENDPOINT` (tuya_connector + rojeco_connector dùng chung), `OPENROUTER_API_KEY` (ai_parser), `DATABASE_URL` (core/database.py), `SUPABASE_URL` (verify ES256 qua JWKS) / `SUPABASE_JWT_SECRET` (HS256 cũ) + `ADMIN_EMAILS` + `APP_TOKEN_SECRET` + `AUTH_DISABLED` (core/auth.py).
  - ⚠️ **Xác thực TỰ SUY, không mặc định bật.** `AUTH_DISABLED` không đặt ⇒ suy từ `SUPABASE_JWT_SECRET`: thiếu secret thì backend **không verify nổi token**, bật xác thực chỉ làm mọi request 401 và app cả nhà chết. Mà service Render được tạo tay trên dashboard nên **KHÔNG đọc `render.yaml`** — quên set biến là đủ gây sự cố thật. Có secret ⇒ tự bật. Đặt `AUTH_DISABLED=0` tường minh để ép bật kể cả khi thiếu secret (fail closed). Lifespan log to trạng thái mỗi lần boot: `🔒 Xác thực BẬT` / `🔓 Xác thực TẮT`.
  - `ADMIN_EMAILS` (phân tách dấu phẩy) là **cứu hộ cấp env**: các email này luôn thành `owner`/`active` mỗi lần đăng nhập, kể cả khi vai trong DB bị hạ. Trên Render set qua Dashboard > Environment. Lifespan bọc try/except từng connector — 1 hãng lỗi không sập app; Tuya/Rojeco `connect()` chạy `asyncio.to_thread` và chỉ set `is_connected` khi token response `success`.

---

## Bảng trạng thái Database

| Table | Status | Ghi chú |
|---|---|---|
| devices (`DeviceModel`) | ✅ | id (PK = id hãng), name, brand, is_active, **zone_id** (FK zones, ON DELETE SET NULL, NULL = "hộp thư đến"), **category** (`purifier`\|`curtain`\|`feeder`\|`switch`, NULL = suy từ tên; PATCH validate → 400). `seed_defaults()` nạp 3 thiết bị (kèm category) khi bảng rỗng, giữ nguyên id. |
| zones (`ZoneModel`) | ✅ | id, name, sort_order. `seed_defaults()` tạo khu 'Nhà' khi bảng rỗng và gán thiết bị chưa phân khu vào đó. |
| members (`MemberModel`) | ✅ | user_id (PK, = auth.users.id dạng text), email, display_name, role (owner\|adult\|kid\|guest), status (pending\|active\|blocked). |
| member_zone_access (`MemberZoneAccessModel`) | ✅ | (user_id, zone_id) PK ghép. Grant CHỈ cho kid/guest — owner/adult thấy mọi khu theo luật vai nên không có hàng nào ở đây. |
| schedules (`ScheduleModel`) | ✅ | id, name, brand, device_id, action_type, action_value, time, days, enabled, last_fired_date + end_time, end_action_type, end_action_value, last_end_fired_date, one_shot, **created_by** (lịch khoảng/one-shot; cột mới qua `run_startup_migrations`, chạy được trên cả SQLite lẫn Postgres). |

**Nơi lưu:** `DATABASE_URL` → Postgres (Supabase); không đặt → SQLite `backend/smarthome.db`.
⚠️ Còn chạy SQLite trên Render thì **lịch hẹn mất mỗi lần redeploy** (ổ đĩa ephemeral + file DB bị track trong git). Log lúc boot nói rõ đang dùng loại nào và cảnh báo nếu là SQLite. Cách khắc phục: `backend/docs/SUPABASE_SETUP.md`.
