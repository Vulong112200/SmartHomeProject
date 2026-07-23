# Features — Danh sách chức năng & trạng thái

> Cập nhật qua `/sync-docs`. Mỗi feature có format chuẩn: **Status / Backend / Frontend / Key logic**.

## Format chuẩn

```
### <Tên feature>
- **Status:** 📋 planned | 🚧 in progress | ✅ done
- **Backend:** model · service · endpoints liên quan
- **Frontend:** core · screens · widgets · native
- **Key logic:** điểm logic quan trọng/dễ sai
```

---

## Features

### Đa người dùng (Supabase Auth + multi-tenant)
- **Status:** ✅ done (code hoàn chỉnh; cần thiết lập Supabase 1 lần để chạy thật — `SUPABASE_SETUP.md`)
- **Backend:** `core/auth.py` (`get_current_user`/`require_admin` — verify JWT HS256 Supabase, `AUTH_DISABLED=1` dev bypass) · `core/crypto.py` (Fernet `encrypt_json`/`decrypt_json`) · `core/database.py` (`DATABASE_URL` chọn SQLite/Postgres, `init_db`, `run_startup_migrations`) · `models/vendor_account.py` (`VendorAccountModel`) · `services/connector_factory.py` (`get_user_connector`, `discover_vesync`, `invalidate_user`) · endpoints `/api/me`, `/api/vendor/*`, `/api/devices/import`, `/api/admin/*` (`main.py`) · `backend/docs/supabase_schema.sql` + `SUPABASE_SETUP.md` · test `backend/tests/test_multiuser_scope.py` (37/37 pass).
- **Frontend:** `core/auth_service.dart` (Supabase Auth + `authHeaders()` Bearer) · `core/vendor_api.dart` (client vendor/admin) · `screens/login_screen.dart` + `AuthGate` (`main.dart`) · `screens/add_device_screen.dart` (khám phá) · `screens/admin_screen.dart` (quản trị) · `dashboard_tab.dart` (tên user động + nút Thêm thiết bị + menu đăng xuất/Quản trị) · `DeviceApi`/`ScheduleApi`/inline calls đã gắn token · `device_order.dart` khóa theo `user.id`.
- **Key logic:**
  - Mọi bảng ứng dụng (`devices`, `schedules`, `vendor_accounts`) có cột `user_id` (TEXT = `auth.users.id`); MỌI endpoint (kể cả `DELETE`/`run` lịch) đều `Depends(get_current_user)` và lọc theo `user.user_id`. Điều khiển/đọc trạng thái kiểm tra sở hữu qua `_get_owned_device` trước khi chạm connector. `is_admin` = email token ∈ `ADMIN_EMAILS`.
  - **DB kép**: `DATABASE_URL` rỗng → SQLite local (`smarthome.db`, `create_all` + `run_startup_migrations` ALTER cột thiếu — idempotent); có giá trị → Postgres/Supabase, schema quản lý qua file SQL riêng (KHÔNG chạy `run_startup_migrations`), có RLS (`*_owner` policies + `is_admin()`) làm phòng thủ thứ hai dù backend đã tự scope bằng connection string vai trò postgres (bỏ qua RLS).
  - **Connector theo user** (`connector_factory.get_user_connector`): Tuya/Rojeco dùng chung 1 project Tuya → connector **singleton** (đăng ký ở `connector_manager` lúc lifespan). VeSync đăng nhập theo TỪNG tài khoản → connector tạo lười, cache theo `user_id` trong dict module-level `_vesync_cache` (mất khi restart server, tự login lại), credential giải mã từ `vendor_accounts.credentials_encrypted` bằng `core/crypto.py` (Fernet, khóa `FERNET_KEY`).
  - VeSync connector KHÔNG còn khởi tạo lúc lifespan (trước đây dùng `VESYNC_EMAIL/PASSWORD` chung) — biến env đó không còn tác dụng; mỗi user tự nhập qua `/api/vendor/vesync/connect`.
  - **Khám phá thiết bị**: VeSync tự phục vụ (`vesync_connector.list_devices()` qua `discover_vesync` → `/api/vendor/vesync/connect` → chọn → `/api/devices/import`). Tuya bán tự động (Tuya bỏ API login email/pass): user quét QR liên kết app account → admin xem `/api/admin/tuya/linked` (`list_app_users`/`list_user_devices`) → gán `tuya_uid` (`/api/admin/vendor/tuya/assign`) → user `/api/vendor/tuya/discover` để chọn import.
  - Migrate dữ liệu SQLite cũ sang Supabase: xem hướng dẫn cuối `SUPABASE_SETUP.md` (chèn lại thiết bị kèm `user_id` admin, hoặc dùng lại luồng "Thêm thiết bị" sau khi có tài khoản).

### Hẹn giờ thiết bị (schedule server-side: đơn + khoảng)
- **Status:** ✅ done
- **Backend:** `ScheduleModel` (`models/schedule.py`, bảng `schedules`) · `services/scheduler.py` (`scheduler_loop` + `execute_schedule_action` + `_is_time_due`/`_end_days`) · `run_startup_migrations` (`core/database.py`) · `/api/schedules` GET/POST/PATCH/DELETE + `/api/schedules/{id}/run?part=start|end` + helper `_create_schedule_row` (`main.py`) · test `backend/tests/test_scheduler_helpers.py`.
- **Frontend:** `core/schedule_api.dart` (`Schedule` model + `ScheduleApi`) · `screens/schedule_tab.dart` (tab thứ 3 "Hẹn giờ": list + form bottom-sheet) · `main.dart` (NavigationDestination + IndexedStack).
- **Key logic:**
  - **Hẹn giờ ĐƠN**: 1 lịch = 1 thiết bị + 1 giờ (`"HH:MM"` giờ VN) + 1 hành động (`on`/`off`/`mode`+value) + ngày lặp (`days` CSV 0=Thứ2…6=CN, rỗng = mỗi ngày).
  - **Hẹn giờ KHOẢNG**: thêm `end_time` + `end_action_type/value` — 2 mốc trong 1 lịch (vd 16:30 lọc Cao → 17:30 lọc TB). `end_time` NULL = lịch đơn (backward compatible). **Qua đêm**: `end_time < time` hợp lệ, end kích hoạt NGÀY HÔM SAU — ngày check end dịch +1 mod 7 (`_end_days`); chỉ chặn end == start. Start và end bắn ĐỘC LẬP, mỗi mốc có fired-date riêng (`last_fired_date`/`last_end_fired_date`) → restart giữa khoảng vẫn trả thiết bị về trạng thái "sau".
  - **One-shot** (`one_shot=True`): lịch đơn tự `enabled=False` sau start; lịch khoảng tắt sau end. Lỡ trọn cửa sổ của hành động cuối (server ngủ) → tự tắt + log "lịch 1 lần đã lỡ giờ" (tránh bắn nhầm tuần sau cùng thứ). Dùng cho lịch tạo từ giọng nói.
  - Cột mới thêm bằng `run_startup_migrations(engine)` gọi ngay sau `create_all` trong `main.py` — ALTER TABLE cột thiếu, idempotent (create_all KHÔNG alter bảng đã tồn tại).
  - Vòng lặp asyncio khởi động trong **lifespan** (`main.py`), tick **30s**: mốc "đến giờ" khi `0 <= now - giờ hẹn < 120s` (grace) VÀ fired-date != hôm nay. **Đánh dấu fired-date TRƯỚC khi gửi lệnh** → lệnh chậm/lỗi không bắn lặp (an toàn với motor cửa). Lỗi 1 lịch không dừng vòng lặp; start xử lý trước end trong cùng tick (khoảng ngắn hơn grace vẫn đúng thứ tự).
  - Hành động tái dùng nguyên primitive connector (`turn_on`/`turn_off`/`set_mode`) + `_cache_invalidate` sau lệnh (truyền callback từ main.py, tránh circular import).
  - PATCH đổi `time`/bật `enabled` → reset `last_fired_date`; đổi `end_time`/bật enabled → reset `last_end_fired_date`; gửi `end_time: null` TƯỜNG MINH → xóa sạch bộ end (thành lịch đơn). Validate merged (giá trị mới ưu tiên, thiếu lấy từ row): action ∈ on/off/mode, mode cần value (cùng luật cho bộ end), time regex HH:MM, days CSV 0-6, có end_time thì bắt buộc end_action_type.
  - `/run` chạy ngay để test (KHÔNG đổi fired-date); `?part=end` chạy hành động kết thúc (lỗi rõ nếu lịch đơn). `DELETE` và `POST /run` đều đã có `Depends(get_current_user)` + lọc `user_id`; `POST /run` gọi `execute_schedule_action(db, sch.user_id, sch.brand, sch.device_id, ...)` đúng chữ ký hiện tại của `scheduler.py`.
  - GET/POST/PATCH schedules đã lọc/gắn `user_id` (đa người dùng); POST kiểm tra `device_id` thuộc user (`_get_owned_device`) trước khi tạo lịch.
  - Múi giờ cố định `ZoneInfo("Asia/Ho_Chi_Minh")` (server Render chạy UTC) — cần `tzdata` trong requirements.
  - ⚠️ Phụ thuộc server luôn thức (UptimeRobot ping `/health`); ổ đĩa Render free ephemeral → lịch mất khi **redeploy** (nâng cấp DB ngoài nếu cần bền).
  - Form frontend: `SegmentedButton` "Một mốc"/"Khoảng"; Khoảng hiện thêm tile Giờ kết thúc + chip Hành động kết thúc (đổi thiết bị reset cả 2 action key); end == start chặn bằng snackbar, end < start hiện ghi chú "Kết thúc vào ngày hôm sau (lịch qua đêm)". Card khoảng hiện `"16:30 → 17:30"` (fontSize 18, qua đêm thêm `⁺¹`) + `"Lọc Cao → Lọc TB • <tên>"` (`_actionSummary`); tag "1 lần" khi `oneShot`. Hành động theo **loại thiết bị** (`device_type.dart`): máy lọc = Bật/Tắt/Thấp/TB/Cao/Auto/Ngủ; cửa = Mở/Đóng; máy ăn = Nhả 1-3 phần. Tap card để sửa; Switch bật/tắt lịch (PATCH); nút xóa có dialog xác nhận.

### Quản lý thiết bị (devices)
- **Status:** ✅ done (đã lọc theo user_id — xem feature "Đa người dùng" cho ngữ cảnh multi-tenant)
- **Backend:** `DeviceModel` (`models/device.py`) · `/api/devices` GET/POST/DELETE (`main.py`, đều `Depends(get_current_user)` + lọc `user_id`).
- **Frontend:** `device_api.dart` (`fetchDevices`/`fetchStatus`/`sendMode`/`sendAction`) · `dashboard_tab.dart` (list + card).
- **Key logic:** DeviceModel có `user_id` (chủ sở hữu), `category` (cột mới, tùy chọn — CHƯA dùng ở frontend), `sort_order`, `created_at`; loại thiết bị hiển thị vẫn suy từ TÊN phía client qua `core/device_type.dart` (**nơi duy nhất**: 'lọc'→airPurifier, 'cửa'→curtain, 'mèo'/'ăn'→feeder) — dùng chung bởi dashboard, widget_service, schedule_tab. Card máy lọc & cửa có nhãn trạng thái sống (`statusLabel`) đọc từ `/status`. Base URL/timeout gom về `core/config.dart` (`AppConfig`). ⚠️ Frontend hiện KHÔNG gửi Authorization header nên các request sẽ 401 trừ khi backend bật `AUTH_DISABLED=1`.

### Điều khiển bật/tắt & chế độ
- **Status:** ✅ done
- **Backend:** `/api/test-control/{brand}/{id}?action=` và `/mode?mode=` (`main.py`) → `_get_owned_device` (kiểm tra sở hữu) → `connector_factory.get_user_connector(db, user_id, brand)` → `turn_on/turn_off/set_mode`.
- **Frontend:** `DeviceApi.sendMode`/`sendAction` · nút mode + switch trong `dashboard_tab.dart`.
- **Key logic:**
  - Endpoint kiểm tra `bool` connector trả về — lệnh thất bại → `{status:"error"}` (không còn luôn "success"). `DeviceApi._isOk` đọc `body['status']` chứ không chỉ HTTP 200.
  - Connector không còn resolve tĩnh qua `device_manager` — đi qua `connector_factory.get_user_connector` để VeSync dùng đúng tài khoản của user (Tuya/Rojeco vẫn singleton chung project). Lỗi resolve (chưa kết nối VeSync) ném `ValueError` → endpoint bắt riêng, trả `{status:"error", message:...}`.
  - Frontend: `_sending` chặn double-tap; `_pendingMode` tô sáng lạc quan nút vừa bấm. **Reconcile theo giá trị**: `_refreshStatus` chỉ xóa `_pendingMode` khi `_currentModeValue(status thật)` KHỚP mode vừa bấm (hoặc quá hạn `_pendingSince` ~10s) → highlight KHÔNG nhảy về mode cũ khi cloud chưa propagate. `_refreshAfterCommand` poll lại nhiều nhịp (~0.7/1.3/2/3s) với `fresh=true` (bỏ cache), dừng sớm khi đã khớp.
  - Nút cửa (Mở/Dừng/Đóng) KHÔNG bị khóa — luôn bấm được; tô sáng nút khớp `door_state` (`activeDoorMode`). Backend tự chèn `stop` trước open/close nên an toàn.
  - Connector Tuya/Rojeco dùng `asyncio.to_thread` cho call HTTP đồng bộ → không block event loop. Mode phụ thuộc brand (tuya: open/close/stop; vesync: low/med/high/auto/sleep/off).

### Trạng thái sống thiết bị
- **Status:** ✅ done
- **Backend:** `/api/devices/{brand}/{id}/status` (`main.py`, opt `?fresh=1` bỏ cache) → `connector_factory.get_user_connector` → `connector.get_device_state`; cache in-memory TTL ~3s (`_status_cache`, key `(user_id, brand, device_id)` — tránh rò rỉ trạng thái giữa các user), tự xóa sau mỗi lệnh điều khiển.
- **Frontend:** `DeviceApi.fetchStatus(brand, id, {fresh})` (`device_api.dart`) — dùng ở dashboard & shortcut handler; card máy lọc/cửa tự động poll `Timer.periodic(6s)` (dùng cache), refresh sau lệnh dùng `fresh:true`. **Poll tự tạm dừng** khi tab Home ẩn (`DashboardTab.isVisible` từ IndexedStack) hoặc app vào nền (`WidgetsBindingObserver`), refresh ngay khi hiển thị lại (`didUpdateWidget` + `_setPolling`). Card báo ON/OFF thật về parent qua `onStatusChanged` → header đếm "Đang bật" chính xác (trước đây chỉ đếm `is_active` tĩnh).
- **Key logic:** shape khác nhau theo brand; field chung là `status` (ON/OFF/offline). Tuya thêm `door_state`/`position`; VeSync thêm `mode`/`speed`. ⚠️ Rojeco stub luôn "ON".
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
  - 3 khe cố định theo loại: p=máy lọc (contains 'lọc'), c=cửa (contains 'cửa'), f=máy cho ăn (contains 'mèo'/'ăn'). Khe không có thiết bị → ẩn (`{slot}_visible`).
  - Dữ liệu đẩy qua `HomeWidget.saveWidgetData` (string), vẽ lại bằng `updateWidget(qualifiedAndroidName: com.example.frontend.SmartHomeWidgetProvider)`.
  - Nút bấm → `HomeWidgetBackgroundIntent` (URI `smarthome://action?type&brand&id` hoặc `smarthome://refresh`) → `widgetBackgroundCallback` (@pragma vm:entry-point) chạy NỀN, gọi DeviceApi rồi `refreshAll()` cập nhật lại. KHÔNG mở app.
  - App đang mở: `dashboard_tab.fetchDevices` thành công → `WidgetService.refreshAll()` đồng bộ widget.
  - ⚠️ Giới hạn: chỉ hiện 1 thiết bị/loại (nếu có 2 máy lọc chỉ hiện 1). Trạng thái phụ thuộc backend (Render free có thể ngủ → "Không rõ").

### Automation engine
- **Status:** 📋 planned (đóng băng)
- **Backend:** `automation_engine.py` — không được import trong `main.py`.
- **Key logic:** chưa kích hoạt; tính năng Hẹn giờ dùng `services/scheduler.py` riêng (persist DB) thay vì engine này (rule in-memory).

### Cấu hình & bảo mật (env)
- **Status:** ✅ done
- **Backend:** `load_dotenv()` đầu `main.py` · `backend/.env` (thật, gitignore) · `backend/.env.example` (mẫu).
- **Key logic:** `TUYA_ACCESS_ID/KEY/API_ENDPOINT` (+ `TUYA_APP_SCHEMA` tùy chọn — tuya_connector + rojeco_connector dùng chung), `OPENROUTER_API_KEY` (ai_parser), và bộ multi-user `DATABASE_URL`/`SUPABASE_JWT_SECRET`/`FERNET_KEY`/`ADMIN_EMAILS`/`AUTH_DISABLED` (xem feature "Đa người dùng"). ⚠️ `VESYNC_EMAIL/PASSWORD` KHÔNG còn dùng (đã bỏ khỏi lifespan). Trên Render set qua Dashboard > Environment. Lifespan bọc try/except từng connector (Tuya/Rojeco) — 1 hãng lỗi không sập app; `connect()` chạy `asyncio.to_thread` và chỉ set `is_connected` khi token response `success`.

---

## Bảng trạng thái Database

| Table | Status | Ghi chú |
|---|---|---|
| devices (`DeviceModel`) | ✅ | id (vendor device id), user_id, name, brand, category (tùy chọn, chưa dùng ở FE), is_active, sort_order, created_at. |
| schedules (`ScheduleModel`) | ✅ | id, user_id, name, brand, device_id, action_type, action_value, time, days, enabled, last_fired_date + end_time, end_action_type, end_action_value, last_end_fired_date, one_shot (lịch khoảng/one-shot). Cột SQLite mới qua `run_startup_migrations`; Postgres qua `supabase_schema.sql`. ⚠️ Ephemeral trên Render free NẾU dùng SQLite (mất khi redeploy) — Postgres/Supabase thì bền. |
| vendor_accounts (`VendorAccountModel`) | 🚧 | id, user_id, brand (vesync\|tuya), credentials_encrypted (Fernet), tuya_uid, label, status, created_at. Model + schema đã có nhưng **chưa có endpoint ghi vào bảng này** — không tạo được qua API hiện tại. |
