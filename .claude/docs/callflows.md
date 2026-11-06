# Callflows — Luồng hoạt động chính

> Cập nhật qua `/sync-docs`. Mô tả chuỗi UI → service → backend → connector → thiết bị → response.

## 1. Tạo & bấm Shortcut thiết bị (Android)

**Tạo shortcut:**
```
dashboard_tab.dart: _buildShortcutButton (iconRes = ShortcutIcons.<type>(state))
  → _createShortcut → ShortcutService.pinShortcut(action, label, iconRes)
    → MethodChannel 'smarthome/shortcuts'.invokeMethod('pinShortcut', {id, labels, iconRes, ...action})
      → MainActivity.buildShortcut: tạo ShortcutInfoCompat
           Intent(ACTION_VIEW → MainActivity) + extras(type/brand/deviceId/deviceName)
           setIcon(resolveIcon(iconRes))   # tra drawable theo tên; thiếu → launcher_icon
        → ShortcutManagerCompat.requestPinShortcut  # hệ thống hỏi "thêm vào màn hình chính"
```

**Bấm shortcut trên màn hình chính:**
```
Launch MainActivity với intent extras
  ├─ cold start: getInitialAction → ShortcutService._consumeInitialAction
  └─ đang chạy: onNewIntent → invokeMethod('onShortcutAction', map)
    → ShortcutService._dispatch → ShortcutHandler.handle(action)  (switch theo action.type)
      ├─ purifierCycle: fetchStatus → PurifierCycle.next → apply(/mode) → updateShortcutIcon(step)
      ├─ doorToggle:    fetchStatus → hỏi chiều ngược → sendMode(open/close) → updateShortcutIcon(icon lạc quan)
      │                    → _reconcileDoorIcon: chờ ~2s → fetchStatus(fresh) → updateShortcutIcon(door_state THẬT)
      ├─ doorOpen/doorClose/feederFeed: _confirm dialog → DeviceApi.sendMode
      └─ updateShortcutIcon → MethodChannel 'updateShortcut' → ShortcutManagerCompat.updateShortcuts
```
Ghi chú: dialog/snackbar hiện qua `appNavigatorKey` (global) vì có thể app vừa mở do bấm icon (`_waitForContext` chờ Navigator sẵn sàng).

## 1b. Home Screen Widget (App Widget)

**Đẩy trạng thái lên widget (app đang mở hoặc khởi động):**
```
main.dart WidgetService.init()  hoặc  dashboard fetchDevices() thành công
  → WidgetService.refreshAll(): DeviceApi.fetchDevices → phân loại khe (p/c/f)
       → mỗi khe: DeviceApi.fetchStatus → nhãn trạng thái → HomeWidget.saveWidgetData
  → HomeWidget.updateWidget(qualifiedAndroidName: ...SmartHomeWidgetProvider)
    → SmartHomeWidgetProvider.onUpdate đọc SharedPreferences → RemoteViews (ẩn khe {slot}_visible=0)
```

**Bấm nút trên widget (chạy nền, KHÔNG mở app):**
```
Nút widget (PendingIntent = HomeWidgetBackgroundIntent, URI smarthome://action?type&brand&id | smarthome://refresh)
  → HomeWidgetBackgroundReceiver → HomeWidgetBackgroundService (isolate nền)
    → widgetBackgroundCallback(uri) → WidgetService.handleUri
      ├─ action: _performAction (purifierCycle/doorToggle/feederFeed) qua DeviceApi
      └─ refresh: bỏ qua action
    → refreshAll() cập nhật lại widget
```

## 2. Lệnh giọng nói (AI parse)

```
ai_assistant_tab.dart (speech-to-text) → POST /api/ai/parse {text}
  → main.py: firewall device_keywords + "hẹn"/"lịch" (không có từ khóa → trả rỗng, bỏ qua AI)
  → câu đơn: parse_command_locally(text, devices)
  → câu phức (và/rồi/với/nhưng) hoặc local rỗng: parse_command_with_ai (OpenRouter)
  → execute_single_action cho mỗi action (asyncio.gather song song)
       ├─ intent == "schedule" → _create_schedule_from_intent (xem 2b, KHÔNG gọi connector)
       └─ còn lại: nhận cả action = on|off (AI) LẪN turn_on|turn_off (local parser)
            connector.turn_on/turn_off/set_mode theo brand → _cache_invalidate(brand, id)
  → trả {ai_understood, execution_results:[{device_name, action, success}]}
```

## 2b. Giọng nói TẠO lịch hẹn ("hẹn 16 giờ 30 bật quạt lọc mức cao")

```
parse_command_locally (local_parser.py)
  → extract_schedule_times(text) (vn_time_parser.py)
       ├─ None (không có giờ) → _extract_device_actions(text) → thi hành NGAY (đường cũ)
       └─ có giờ → CHỈ trả intent schedule (không bao giờ thi hành ngay):
            _extract_device_actions(cleaned_text)   # cụm giờ/buổi/ngày đã bị cắt
            ├─ rỗng → [] (AI fallback thử, prompt có few-shot schedule cùng shape)
            └─ khoảng "từ X đến Y": head/tail 2 hành động (tail thiếu thiết bị → ghép _BRAND_HINT);
                 1 hành động → end mặc định turn_off (cửa open→close; cửa close/stop → lịch đơn)
  → execute_single_action thấy intent == "schedule"
    → _create_schedule_from_intent (main.py):
         verb → cột lịch (turn_on/on→on, turn_off/off→off, set_mode→mode+value)
         resolve_target_days(time, day_offset, recurring, now VN)
           ├─ "mỗi ngày" → days rỗng, one_shot=False
           └─ còn lại → days = thứ ngày đích, one_shot=True (giờ đã qua hôm nay → roll sang mai)
         _create_schedule_row (validate + INSERT, dùng chung POST /api/schedules)
    → bubble "Đã hẹn [ngày mai ]16:30 • Chế độ 3" / "Đã hẹn 16:30→17:30 • ..., kết thúc: Tắt"
       (lỗi validate → "Lỗi hẹn giờ: ..." success=False; KHÔNG chạm connector/cache)
  → lịch hiện trong tab Hẹn giờ; scheduler_loop kích hoạt như lịch thường (one-shot tự tắt sau khi chạy)
```

## 3. Điều khiển trực tiếp từ Dashboard

```
dashboard_tab.dart (nút mode / switch bật-tắt)
  ├─ chặn double-tap: _sending==true → bỏ qua; tô sáng ngay nút vừa bấm (_pendingMode, lạc quan)
  → DeviceApi.sendAction/sendMode (GET /api/test-control/{brand}/{id}?action=  hoặc  /mode?mode=)
  → main.py → device_manager.get_connector(brand) → turn_on/turn_off/set_mode (trả bool)
       ├─ ok==false → trả {status:"error"} (KHÔNG còn luôn "success")
       └─ invalidate cache trạng thái (brand,id)
  → connector gọi cloud của hãng qua asyncio.to_thread (Tuya/Rojeco đồng bộ → không block event loop)
  ← _isOk() đọc body['status']=='success' (không chỉ HTTP 200)
  → _refreshAfterCommand: poll lại nhiều nhịp (~0.7/1.3/2/3s) với fresh=true (bỏ cache),
       dừng sớm khi trạng thái thật KHỚP mode vừa bấm
```
Ghi chú quan trọng — reconcile theo GIÁ TRỊ:
- `_pendingMode` (mode vừa bấm) chỉ bị xóa khi `_currentModeValue(status thật) == _pendingMode`
  (cloud xác nhận) HOẶC quá hạn `_pendingSince` (~10s). Nếu chưa khớp → GIỮ tô sáng lạc quan,
  tránh highlight nhảy về mode cũ khi cloud chưa kịp propagate.
- Nút cửa (Mở/Dừng/Đóng) KHÔNG bị khóa — luôn bấm được; nút đang hoạt động được tô sáng
  theo `door_state`/`_pendingMode` (backend tự chèn `stop` trước khi đảo chiều nên an toàn).

## 4. Đọc trạng thái thiết bị

```
dashboard_tab.dart / shortcut_handler.dart → DeviceApi.fetchStatus(brand, id)
  → GET /api/devices/{brand}/{id}/status  (thêm ?fresh=1 để bỏ qua cache)
       ├─ (không fresh) cache còn hạn (<3s) → trả ngay {..., cached:true}
       └─ connector.get_device_state → cache_set → trả về
  → trả {status: success, data: {status, door_state/position | mode/speed}}
```
Ghi chú: card máy lọc & cửa tự động poll `Timer.periodic(6s)` — CHỈ khi `pollingEnabled`
(tab Home hiển thị theo `DashboardTab.isVisible` từ IndexedStack VÀ app foreground theo
`WidgetsBindingObserver`); tab ẩn/app nền → `_setPolling(false)` dừng timer, hiển thị lại →
refresh ngay + poll tiếp (`didUpdateWidget`). Mỗi lần có data → `onStatusChanged` báo ON/OFF
thật về parent để header đếm "Đang bật" đúng.

Cách connector suy trạng thái (đều đọc cloud THẬT, không dùng lịch sử lệnh app):
- VeSync: `purifier.update()` → đọc `device_status`/`mode`/`fan_level` (trạng thái vật lý thật).
- Tuya cửa: đọc DP status từ cloud → ưu tiên **vị trí thật** (`_POSITION_DPS`) → **tình trạng thật**
  (`_WORK_STATE_DPS`) → chỉ fallback DP `control` (lệnh cuối, có thể kẹt) khi không có 2 nguồn trên;
  không nhận ra DP → `unknown` + log `[Tuya Door] ⚠️`.

Đồng bộ icon shortcut theo trạng thái thật (khi app mở): mỗi lần `_refreshStatus` có data →
`dashboard_tab._syncShortcutIcon` đẩy `updateShortcutIcon` cho cửa/quạt (no-op an toàn nếu chưa pin;
`_lastShortcutIcon` chặn gọi lặp) → icon đúng cả khi thiết bị bị điều khiển từ remote vật lý/app khác.

## 5. Hẹn giờ thiết bị (scheduler server-side)

**Tạo/sửa lịch từ app:**
```
schedule_tab.dart (FAB ＋ / tap card) → _ScheduleForm (bottom sheet)
  chọn thiết bị (dropdown từ /api/devices) → loại lịch (SegmentedButton "Một mốc" | "Khoảng")
  → hành động theo loại thiết bị (device_type.dart) → giờ (TimePicker)
  → [Khoảng] giờ kết thúc + hành động kết thúc (end == start chặn snackbar;
       end < start = qua đêm, hiện ghi chú "Kết thúc vào ngày hôm sau")
  → ngày lặp (FilterChip T2..CN → CSV 0-6) → tên tùy chọn
  → ScheduleApi.createSchedule / updateSchedule (POST | PATCH /api/schedules, JSON body;
       edit chuyển Khoảng → Một mốc gửi end_time: null TƯỜNG MINH để xóa khoảng)
    → main.py _create_schedule_row / PATCH validate merged (_validate_schedule_fields:
         action_type, HH:MM, days CSV, bộ end cùng luật, chặn end == start)
    → INSERT/UPDATE bảng schedules; PATCH đổi time/end_time/bật enabled → reset fired-date tương ứng
```

**Vòng lặp kích hoạt (chạy nền trên server):**
```
main.py lifespan → init_db() (try/except -> db_ready) → connectors
  → CHỈ KHI db_ready: asyncio.create_task(scheduler_loop(invalidate_cache=_cache_invalidate))
  → mỗi 30s: now = datetime.now(Asia/Ho_Chi_Minh); duyệt schedules enabled==True
    → start ĐẾN GIỜ khi: weekday ∈ days (hoặc days rỗng) VÀ 0 <= now - time < 120s
                         VÀ last_fired_date != hôm nay
    → end ĐẾN GIỜ khi:   có end_time VÀ weekday ∈ _end_days (qua đêm: days dịch +1 mod 7)
                         VÀ 0 <= now - end_time < 120s VÀ last_end_fired_date != hôm nay
    → mỗi mốc: đánh dấu fired-date + commit TRƯỚC khi gửi lệnh (chống bắn lặp);
         one_shot: lịch đơn tắt sau start, lịch khoảng tắt sau end;
         one_shot lỡ trọn cửa sổ mốc cuối (server ngủ) → enabled=False + log (không bắn tuần sau)
    → execute_schedule_action: device_manager.get_connector(brand)
         → turn_on / turn_off / set_mode(device_id, action_value)
    → _cache_invalidate(brand, device_id)  # app đọc được trạng thái mới ngay
```
Ghi chú: server được UptimeRobot ping /health giữ thức (Render free-tier). Lịch lưu SQLite —
ephemeral trên Render, mất khi redeploy. `/api/schedules/{id}/run` chạy ngay để test (không
đổi fired-date; `?part=end` chạy hành động kết thúc). Start xử lý trước end trong cùng tick
nên khoảng ngắn hơn grace vẫn đúng thứ tự. Restart giữa khoảng: end vẫn bắn độc lập → thiết bị
về trạng thái "sau" như mong muốn.

## 4b. Khởi động app (warm-up server)

```
dashboard_tab.dart _bootstrap() (initState)
  → isWaking=true, hiện "Đang đánh thức máy chủ..." (thay vì treo im lặng)
  → GET /health (timeout 35s) đánh thức Render free-tier đang ngủ
  → isWaking=false → fetchDevices()
```

## 4c. Sắp xếp thứ tự thiết bị (kéo-thả, đồng bộ theo tài khoản)

```
Tải danh sách:
  AuthGate GET /api/me → profile.sortOrder        # backend: device_order_of = members.sort_order ∩ device_query
  fetchDevices → _resolveOrder()
       lần đầu: DeviceOrderSync.restore()   (bản chờ 'device_order_pending_v2:<uid>' từ phiên trước → flush)
                tài khoản chưa có thứ tự + còn 'device_order_v1' → schedule(v1) 1 lần; xóa v1
       → sync.pending ?? _accountOrder
       (authEnabled=false → DeviceOrder.load() cục bộ như cũ)
    → DeviceOrder.apply(devices, order): sắp theo id; thiết bị mới → cuối; id đã xóa/mất quyền bị bỏ
    → render SliverReorderableList (item key=ValueKey(id); proxyDecorator = Material bo góc + bóng)
  Kéo xuống làm mới → _pullToRefresh: fetchMe() (khi không có bản chờ) → _accountOrder mới → fetchDevices

Kéo đổi chỗ (chỉ ở chip "Tất cả"):
  kéo TAY CẦM riêng (dragHandle = ReorderableDragStartListener, tránh xung đột cử chỉ với nút/switch)
    → onReorderItem(oldIndex, newIndex)  [newIndex đã điều chỉnh]
    → _onReorder: devices.removeAt/insert (setState — lạc quan)
    → DeviceOrderSync.schedule(ids): lưu bản chờ xuống SharedPreferences, hẹn 2s (kéo tiếp → hủy hẹn cũ)
    → hết 2s / app vào nền / rời tab / dispose → flush()
         → HouseholdApi.saveDeviceOrder → PATCH /api/me {"sort_order": ids}
              backend: >500 / id >128 ký tự → 400; sanitize_device_order (khử trùng, bỏ id lạ/ngoài quyền)
         → ok: xóa bản chờ (chỉ khi không có bản mới hơn)
         → lỗi: giữ bản chờ, thử lại 5s → 15s → 60s; fetchDevices thành công → gửi ngay
```

## 6. Khởi động backend (lifespan → init_db)

```
uvicorn app.main:app
  → import app.main
      core/database.py (tầng import):
        DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", ""))
          rỗng          → "sqlite:///./smarthome.db"
          "postgres://" → đổi thành "postgresql://"   # SQLAlchemy 2.x chỉ nhận dạng này
        engine = make_engine(url)
          sqlite   → connect_args check_same_thread=False
          postgres → pool_pre_ping + pool_recycle=1800 + pool_size=5
      ⚠️ KHÔNG chạm DB ở tầng import: exception ở đây làm uvicorn chết với
         "Error loading ASGI app", không route nào chạy, kể cả /health.

  → lifespan(app)  [try/except → cờ db_ready]
      log "Đang khởi tạo Database (SQLite|Postgres)..."
      init_db():
        1. Base.metadata.create_all(bind)        # checkfirst=True → no-op nếu SQL file đã apply
        2. run_startup_migrations(bind)          # ALTER TABLE cột thiếu; DDL theo dialect
        3. verify_schema(bind)                   # raise kèm tên bảng/cột thiếu
        4. enable_rls(bind)                      # chỉ Postgres; ENABLE RLS, KHÔNG viết policy
        5. seed_defaults(bind)                   # 3 thiết bị nếu bảng devices rỗng, giữ nguyên id
        ⚠️ verify (3) phải TRƯỚC seed (5): ngược lại schema lệch làm seed ném
           OperationalError thô, che mất thông báo nói rõ thiếu cột nào.
      thành công → db_ready=True; nếu IS_SQLITE → log WARNING cảnh báo mất dữ liệu khi redeploy
      thất bại   → db_ready=False, KHÔNG raise (boot degraded)

  → khởi động connector (mỗi hãng bọc try/except riêng — 1 hãng lỗi không sập app)
  → scheduler_task = create_task(scheduler_loop()) CHỈ KHI db_ready
       (db lỗi mà vẫn chạy thì tick 30s log stack trace vĩnh viễn)

  → GET /health → {"status":"online", "db": db_ready}   # LUÔN 200
```

## 7. Phân quyền theo khu vực (mọi request đã đăng nhập)

```
Request có Bearer token
  → core/auth.py get_current_user()
      auth_disabled()?  (AUTH_DISABLED tường minh > bật khi có SUPABASE_URL hoặc SUPABASE_JWT_SECRET)
        TẮT  → CurrentUser giả, is_admin=True     # giai đoạn chưa gắn đăng nhập
        BẬT  → app-token (iss=smarthome-app, APP_TOKEN_SECRET)?  -> dùng luôn (Widget/shortcut)
                 sub == DEV_USER_ID (cấp lúc xác thực TẮT, mang quyền chủ nhà giả) → 401
               không phải → _decode_supabase_token theo `alg` trong header:
                 ES256/RS256 → khóa công khai JWKS {SUPABASE_URL}/auth/v1/.well-known/jwks.json
                               (PyJWKClient cache), kiểm aud=authenticated + iss  # project của nhà
                 HS256       → SUPABASE_JWT_SECRET                                # project kiểu cũ
                 khác        → 401
               -> sub + email; thiếu/sai token -> 401
      is_admin = email ∈ ADMIN_EMAILS

  → core/household.py get_member()  [Depends]
      provision_member(db, user):
        chưa có hàng members -> tạo guest/pending (người lạ lần đầu)
        email ∈ ADMIN_EMAILS       -> LUÔN nâng owner/active (cứu hộ)

  → get_current_member()  [Depends, dùng ở MỌI endpoint trừ /api/me]
        status blocked -> 403 "Tài khoản đã bị chặn."
        status pending -> 403 "Đang chờ chủ nhà phê duyệt."   # app hiện màn chờ

  → endpoint gọi ĐÚNG MỘT trong các hàm sau (quyền không nằm trong thân endpoint):

     device_query(db, member)              # GET /api/devices, POST /api/ai/parse
       owner|adult -> query(DeviceModel)                       # thấy cả zone_id NULL
       kid|guest   -> INNER JOIN member_zone_access ON zone_id  # NULL tự rơi ra

     require_device_access(db, member, id) # control, status, tạo lịch
       thấy được        -> trả DeviceModel
       có trong nhà      -> 403   # ngoài khu của mình; trong nhà không giấu nhau
       không có trong nhà -> 404

     schedule_query(db, member)            # GET /api/schedules
       lọc theo THIẾT BỊ, KHÔNG theo created_by — lịch là của cả nhà

     require_schedule_write(db, member, id) # PATCH/DELETE /api/schedules
       require_can_schedule  (guest -> 403)
       + thấy được lịch      (ngoài khu -> 403)
       + owner|adult, HOẶC created_by == mình  (kid sửa lịch người khác -> 403)

     require_owner(member)                 # POST/PATCH/DELETE devices, zones, members
       không phải owner -> 403
```

Vai và grant đọc từ DB **mỗi request** ⇒ chủ nhà duyệt/đổi vai/chặn thì có hiệu
lực ngay ở request kế tiếp, không cần đăng nhập lại. Chi phí:
`get_current_member` = 1 select theo PK, `require_device_access` = 1 select có
index. Dashboard poll 6s cho 3 card ≈ 1.5 req/s.

## 8. Khởi động app có đăng nhập (AuthGate) + isolate nền

```
main()
  AppConfig.authEnabled?   (có SUPABASE_URL + SUPABASE_ANON_KEY từ --dart-define)
    KHÔNG → bỏ qua init Supabase             # bản build hiện tại trên máy cả nhà
    CÓ    → await AuthService.init()         # TRƯỚC runApp, nếu không AuthGate
                                             # sẽ nháy màn đăng nhập ở cold start
  runApp → AuthGate

AuthGate._bootstrap()
  !authEnabled                  → ready(HouseholdProfile.openHouse)   # chạy như cũ
  chưa đăng nhập & không app-token → signedOut → LoginScreen
  ngược lại:
    GET /api/me
      200 + status active   → ready(profile) → MainScreen  (+ refreshAppToken nền)
      200 + pending/blocked → pending        → PendingScreen
      401                   → handleUnauthorized() → signedOut
      lỗi mạng / 5xx        → offline        → OfflineScreen   # KHÔNG đăng xuất

LoginScreen.signIn()
  Supabase signInWithPassword
    → AuthService.refreshAppToken():
        POST /api/auth/app-token  (Bearer = access token Supabase)
        → 200: lưu SharedPreferences['app_token_v1']
        → 401/403 (pending/blocked/token cũ): XÓA app-token cũ — widget không dùng tiếp token chủ nhà giả
  → onSignedIn → _bootstrap() lại
```

### Isolate NỀN (Home Widget, shortcut đã pin)

```
Người dùng bấm nút trên Home Widget khi app ĐÃ TẮT
  → Android khởi động isolate nền (@pragma('vm:entry-point'))
      ⚠️ Supabase.instance CHƯA init ở đây, và không được init
         (hai isolate refresh song song -> Supabase xoay vòng refresh token
          -> isolate này vô hiệu hóa token của isolate kia -> đăng xuất ngẫu nhiên)
  → WidgetService._performAction → DeviceApi.sendMode(...)
      → DeviceApi._headers() → AuthService.headers() → accessToken()
          _supabaseReady == false (static của isolate mới)  -> bỏ qua Supabase
          → readAppToken() từ SharedPreferences             -> Bearer <app-token>
  → backend verify app-token (iss="smarthome-app") → điều khiển thiết bị
```

Thiếu app-token thì nhánh này trả `{}` không có header ⇒ 401 ⇒ widget hiện
"Không rõ" và nút bấm **không làm gì, không báo lỗi**. Đó là lý do
`test/auth_service_test.dart` chạy đúng trong điều kiện Supabase CHƯA init.

## 9. Lịch sử điều khiển

### Ghi (mọi lệnh hệ thống gửi)
```
App/Widget/Shortcut → DeviceApi.sendAction/sendMode(..., via)
  → GET /api/test-control/...?via=app|widget|shortcut
      → connector.turn_on/off/set_mode → _cache_invalidate
      → _log_control → command_log.record(source=via, member, success)
Giọng nói / Kịch bản → _execute_device_action(..., db, member, source=voice|scene, detail)
      → execute_schedule_action → command_log.record
Lịch hẹn tự chạy → scheduler._fire → execute_schedule_action → record(source=schedule, member=None)
Chạy thử lịch   → /api/schedules/{id}/run → record(source=schedule, member=người bấm)
record() cũng mark_sent(device_id) → để VeSync không coi hậu quả lệnh mình là "ngoài app"
```

### Đọc + kéo sự kiện ngoài app
```
Menu tài khoản → "Lịch sử điều khiển" → HistoryScreen
  → HistoryApi.fetch() → GET /api/history?limit=50   (timeout app 20s)
      devices = device_query(member)          # chỉ thiết bị mình thấy
      sync_external_events(devices)           # wait_for 10s; mỗi thiết bị ≤ 1 lần/60s
        tuya/rojeco: fetch_event_logs(type 5) + (type 7), 7 ngày   (CHỈ ĐỌC)
          → classify_tuya_logs → _insert_events (bỏ ext_id đã có)
      → command_logs WHERE device_id IN devices ORDER BY at_ms DESC
  → "Tải thêm": ?before_ms=<dòng cuối>&sync=false

Dashboard poll /status (máy lọc VeSync, đọc thật không cache)
  → device_history.observe_state → đổi so với lần trước & không có lệnh 60s → record source=external
```

## 10. Sơ đồ mặt bằng 2D

### Xem + điều khiển
```
Tab "Sơ đồ" lần đầu hiển thị (isVisible) → FloorPlanTab._load
  → song song: DeviceApi.fetchDevices (GET /api/devices, đã lọc khu)
               FloorPlanApi.fetch      (GET /api/floor-plan → visible_layout: devices ∩ device_query)
  → PlanGeometry.fit(plan, khung) → CustomPaint(FloorPlanPainter) + DeviceMarker tại toPx(phòng.xy + thiết bị.xy)
  → đọc /status mọi thiết bị; poll 6s (máy lọc/cửa/công tắc) khi tab hiển thị + foreground
Chạm icon → showDeviceControlSheet (deviceActionOptions theo loại)
  → chọn hành động → DeviceApi.sendMode / sendAction (via=app)
      → GET /api/test-control/... (kiểm quyền, normalize, connector, ghi Lịch sử — y như Dashboard)
  → false  → "Thiết bị không nhận lệnh" (không báo thành công)
  → true   → đọc /status?fresh=1 theo confirmDelays (0,7/1,3/2/3/3 s) tới khi statusConfirms
           → "Đã xác nhận: …" hoặc cảnh báo "chưa báo trạng thái mới"
  (chỉ ValueNotifier của thiết bị đó đổi → chỉ icon + bảng đó vẽ lại)
```

### Sửa (chỉ chủ nhà)
```
Nút "Sửa" (profile.canAdmin) → _draft = _plan; tắt pan/zoom khung nhìn
  kéo: _hitTest (thiết bị > cửa > phòng) → moveDevice (tự đổi phòng, kẹp) | slideDoor | moveRoom (hút 5 cm + khít mép)
  chạm: phòng → thêm cửa / kích thước; cửa → bề rộng / xóa; thiết bị → bỏ khỏi sơ đồ; hàng dưới → pickRoom → placeDevice
  "Lưu" → FloorPlanApi.save → PUT /api/floor-plan (require_owner → sanitize_layout → 400 nếu sai, không ghi)
        → floor_plans id=1 ← JSON; trả về bản đã lọc → thoát chế độ sửa
```

## 11. Chạy kịch bản (có điều kiện)

```
Dashboard chạm thẻ kịch bản → _runScene
  → sceneOpensDoor? → hộp xác nhận "sẽ MỞ CỬA CUỐN" (điều kiện KHÔNG bỏ qua bước này)
  → SceneApi.run → POST /api/scenes/{id}/run (40s timeout)
      → main._run_scene
          devices_by_id = device_query(người chạy)
          scene_conditions.load_stored(scenes.conditions)
            NULL / items rỗng → không điều kiện (kịch bản cũ) → chạy như trước
            JSON hỏng        → broken_result() = unknown → BỎ QUA
            có điều kiện     → evaluate_conditions:
               1. time_range trước (giờ theo timezone của điều kiện, không theo máy chủ)
               2. AND đã có failed / OR đã có passed → KHÔNG đọc thiết bị (tiết kiệm quota)
               3. device_state song song: ngoài quyền/đã xóa → unknown (không đọc);
                  _read_state_fresh (connector.get_device_state, BỎ cache 3s, timeout 12s)
                  offline / lỗi / cửa đang chạy / không rõ → unknown
               4. gộp Kleene AND/OR → passed | failed | unknown
          ≠ passed → logger.info, return {executed:false, results:[], conditions:{result, reason, items}}
                     (KHÔNG chạm connector nào)
          = passed → hành động TUẦN TỰ qua _execute_device_action (ngoài khu → skipped, ghi Lịch sử)
      → executed:false → {status:"skipped", message:"Kịch bản đã bỏ qua: …", data}
  → SceneRunResult.fromResponse → snack (cam = bỏ qua vì điều kiện, đỏ = có lệnh lỗi)

Giọng nói "đi ngủ" → /api/ai/parse → match_scene
  → kịch bản MỞ CỬA → từ chối (trước cả điều kiện)
  → _run_scene (cùng cổng điều kiện) → executed:false → bubble "Kịch bản đã bỏ qua: … <lý do>"
```
