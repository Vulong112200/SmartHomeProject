# Tổng hợp chức năng hệ thống SmartHome

> Cập nhật: 2026-11-05 · Nhánh `release/prod-ready` · Production: `main` = `9ae9de6`, APK `1.1.0+2`
>
> Tài liệu này mô tả **toàn bộ chức năng** của hệ thống: những gì người dùng thấy và làm được trên app (phần UI), và những gì máy chủ xử lý phía sau (phần backend). Chi tiết kỹ thuật sâu hơn nằm ở `CLAUDE.md` và `.claude/docs/{features,callflows,structure}.md`.

---

## Mục lục

1. [Tổng quan & kiến trúc](#1-tổng-quan--kiến-trúc)
2. [Thiết bị đang hỗ trợ](#2-thiết-bị-đang-hỗ-trợ)
3. [Vai trò người dùng & phân quyền](#3-vai-trò-người-dùng--phân-quyền)
4. [Phần UI — ứng dụng di động](#4-phần-ui--ứng-dụng-di-động)
5. [Phần Backend — xử lý phía máy chủ](#5-phần-backend--xử-lý-phía-máy-chủ)
6. [Danh sách API](#6-danh-sách-api)
7. [Cơ sở dữ liệu](#7-cơ-sở-dữ-liệu)
8. [Các luồng hoạt động chính](#8-các-luồng-hoạt-động-chính)
9. [An toàn lệnh & bảo mật](#9-an-toàn-lệnh--bảo-mật)
10. [Vận hành & triển khai](#10-vận-hành--triển-khai)
11. [Giới hạn đã biết](#11-giới-hạn-đã-biết)
12. [Bảng tổng hợp trạng thái tính năng](#12-bảng-tổng-hợp-trạng-thái-tính-năng)

---

## 1. Tổng quan & kiến trúc

Hệ thống điều khiển nhà thông minh **đa hãng** cho một gia đình: gom thiết bị của Tuya, VeSync và Rojeco về một app duy nhất, có điều khiển trực tiếp, giọng nói tiếng Việt, hẹn giờ, kịch bản, widget màn hình chính, phân quyền theo khu và lịch sử điều khiển.

```
┌──────────────────────────┐        HTTPS / WSS         ┌──────────────────────────────┐
│  App Flutter (Android)   │ ─────────────────────────▶ │  Backend FastAPI (Python 3.13) │
│  • Tab Home / AI / Hẹn giờ│ ◀───────────────────────── │  • Render (free tier)         │
│  • Home Widget, Shortcut │                            │  • Scheduler nền (30s)        │
│  • Supabase Auth         │                            │  • Phân quyền theo khu        │
└──────────────────────────┘                            └──────────────┬───────────────┘
                                                                       │
          ┌──────────────────────────┬────────────────────────────────┼───────────────────────┐
          ▼                          ▼                                ▼                       ▼
  Postgres (Supabase Tokyo)   Tuya Cloud API               VeSync Cloud (pyvesync)     OpenRouter (LLM)
  devices, zones, members,    cửa cuốn, máy bơm,           máy lọc không khí           câu lệnh phức
  schedules, scenes, logs     máy cho ăn Rojeco
```

| Thành phần | Công nghệ | Vị trí |
|---|---|---|
| Backend | FastAPI, SQLAlchemy, Python 3.13 | `backend/app/` — chạy `uvicorn app.main:app` |
| Cơ sở dữ liệu | Postgres trên Supabase (production); SQLite khi dev | `backend/app/core/database.py` |
| Xác thực | Supabase Auth (email + mật khẩu), JWT ES256 | `backend/app/core/auth.py`, `frontend/lib/core/auth_service.dart` |
| App | Flutter (Android là chính) | `frontend/lib/` |
| Native Android | Kotlin: shortcut, App Widget, WorkManager | `frontend/android/app/src/main/kotlin/...` |
| Hosting | Render free tier, UptimeRobot ping `/health` giữ thức | `render.yaml` |
| AI | OpenRouter qua thư viện `openai` | `backend/app/services/ai_parser.py` |

---

## 2. Thiết bị đang hỗ trợ

| Loại (category) | Thiết bị thật | Hãng / connector | Lệnh điều khiển | Trạng thái đọc được |
|---|---|---|---|---|
| `purifier` — Máy lọc không khí | Máy lọc VeSync | `vesync` — `vesync_connector.py` | Bật, Tắt, Lọc Thấp (1) / TB (2) / Cao (3), Auto, Ngủ (sleep) | ON/OFF/offline, chế độ, tốc độ quạt |
| `curtain` — Cửa cuốn / rèm | Cửa cuốn (Tuya "Curtain switch" `clkg`) | `tuya` — `tuya_connector.py` | Mở, Dừng, Đóng (**không** nhận bật/tắt) | Đang mở / Đang mở... / Đã đóng / Đang đóng... / Đã dừng / Mở một phần |
| `switch` — Công tắc | Máy bơm tăng áp (công tắc Tuya) | `tuya` — `tuya_connector.py` | Bật, Tắt (DP `switch_1`) | Đang chạy / Đã tắt / Mất kết nối |
| `feeder` — Máy cho ăn | Máy cho mèo ăn Rojeco (Tuya `cwwsq`) | `rojeco` — `rojeco_connector.py` | Nhả 1–3 phần (UI), tối đa 10 phần (giới hạn an toàn) | Sẵn sàng • lần trước N phần / Đang nhả hạt... / Mất kết nối |

**Phân loại thiết bị** (quyết định nút điều khiển, hành động hẹn giờ, khe widget):
- Ưu tiên cột `category` do chủ nhà đặt trong màn Quản trị.
- Nếu trống → tự đoán từ **tên**: "bơm" / "tăng áp" / "công tắc" → công tắc (kiểm trước, vì "tăng áp" chứa "ăn"); "lọc" → máy lọc; "cửa" → cửa cuốn; "mèo" / "ăn" → máy cho ăn.
- Một nơi duy nhất mỗi phía: `frontend/lib/core/device_type.dart` và `backend/app/models/device.py` (`device_kind`).

---

## 3. Vai trò người dùng & phân quyền

Mô hình: **thiết bị thuộc KHU (phòng), thành viên được cấp quyền theo KHU.**

| Vai | Thấy & điều khiển | Hẹn giờ | Kịch bản | Quản trị nhà |
|---|---|---|---|---|
| **Chủ nhà** (`owner`) | Mọi thiết bị, kể cả "Chưa phân khu" | Tạo / sửa / xóa mọi lịch | Tạo / sửa / xóa / chạy | ✅ Thành viên, khu, thiết bị |
| **Người lớn** (`adult`) | Mọi thiết bị, kể cả "Chưa phân khu" | Tạo / sửa / xóa mọi lịch | Tạo / sửa / xóa / chạy | ❌ |
| **Trẻ em** (`kid`) | Chỉ khu được cấp + khu dùng chung | Tạo; chỉ sửa / xóa lịch **của mình** | Chỉ chạy | ❌ |
| **Khách** (`guest`) | Chỉ khu được cấp + khu dùng chung | ❌ Không tạo lịch | Chỉ chạy | ❌ |

Trạng thái tài khoản:
- **`pending`** (chưa thuộc nhà) — người mới tự đăng ký; chỉ thấy màn "Chưa thuộc nhà nào" cho đến khi chủ nhà thêm vào.
- **`active`** — dùng bình thường theo vai.
- **`blocked`** — bị chặn, mọi yêu cầu bị từ chối.

Quy tắc quan trọng:
- **Khu dùng chung** (`is_shared`, biểu tượng 🏠): trẻ em/khách dùng được mà không cần cấp riêng.
- **"Chưa phân khu" (hộp thư đến)**: thiết bị mới chưa gán khu — chỉ chủ nhà/người lớn thấy.
- Thiết bị ngoài khu của mình → báo **403 (không có quyền)**, không giấu sự tồn tại.
- Đổi vai / duyệt / chặn có hiệu lực **ngay ở lần bấm kế tiếp**, không cần đăng nhập lại.
- Email trong `ADMIN_EMAILS` luôn được nâng lại thành chủ nhà mỗi lần đăng nhập (cứu hộ, tránh tự khóa mình).
- Chặn ở API: không tự hạ vai, không tự chặn mình, nhà không bao giờ mất chủ nhà cuối cùng.

---

## 4. Phần UI — ứng dụng di động

### 4.1. Bố cục chung

```
Mở app → AuthGate ──┬─ Đang tải
                    ├─ Chưa đăng nhập ──▶ Màn Đăng nhập / Đăng ký / Quên mật khẩu
                    ├─ Chờ duyệt ───────▶ Màn "Chưa thuộc nhà nào"
                    ├─ Mất mạng ────────▶ Màn Offline (Thử lại — KHÔNG đăng xuất)
                    └─ Sẵn sàng ────────▶ Màn chính: 3 tab dưới đáy
                                           ├─ Home (Dashboard)
                                           ├─ AI Assistant
                                           └─ Hẹn giờ
```

- Lần đầu vào app: **giới thiệu 4 trang** (Chào mừng về nhà · Thiết bị theo khu · Kịch bản & hẹn giờ · Ra lệnh bằng giọng nói), có nút "Bỏ qua".
- Giao diện **Sáng / Tối / Theo hệ thống** (mặc định Tối), icon thanh trạng thái tự đổi theo nền.
- Bản build chưa cấu hình khóa Supabase → bỏ qua đăng nhập, vào thẳng app.

### 4.2. Đăng nhập & tài khoản

| Màn hình | Chức năng |
|---|---|
| **Đăng nhập / Đăng ký** (`login_screen.dart`) | Email + mật khẩu; đăng ký tài khoản mới (vào trạng thái chờ duyệt); lỗi Supabase được dịch sang tiếng Việt; nút hiện/ẩn mật khẩu |
| **Quên mật khẩu** (`forgot_password_screen.dart`) | Nhập email → nhận **mã OTP** qua email → nhập mã + mật khẩu mới (nhập 2 lần) → đăng nhập luôn; có "Gửi lại mã" |
| **Chưa thuộc nhà nào** (`pending_screen.dart`) | Nhắc nhờ chủ nhà thêm vào; nút "Kiểm tra lại", "Đăng xuất" |
| **Offline** (`pending_screen.dart`) | Khi máy chủ không phản hồi: "Thử lại", "Đăng xuất" — không tự đăng xuất |

### 4.3. Tab Home (Dashboard) — `dashboard_tab.dart`

**Đầu trang**
- Lời chào "Welcome Home, <tên> 🖖" + **nút tài khoản** (avatar) mở menu:
  - Email + vai hiện tại
  - **Hồ sơ & giao diện**
  - **Lịch sử điều khiển**
  - **Quản trị nhà** (chỉ chủ nhà)
  - **Đăng xuất** (chỉ khi có đăng nhập)
- **Thẻ thống kê**: số Thiết bị · số Đang bật (trạng thái thật) · số Khu vực.

**Hàng kịch bản**
- Mỗi kịch bản là một thẻ: chạm để chạy, kết quả báo bằng snackbar.
- Kịch bản có **mở cửa cuốn** → hỏi xác nhận "Kịch bản này sẽ MỞ CỬA CUỐN".
- Chủ nhà/người lớn: thẻ "+ Kịch bản" để tạo mới, **giữ lâu** thẻ để sửa/xóa.

**Chip lọc theo khu**
- "Tất cả N" + mỗi khu dạng "Phòng khách 1/3" (1 đang bật trên 3 thiết bị); khu dùng chung có biểu tượng 🏠.

**Danh sách thẻ thiết bị** (kéo xuống để tải lại)

| Loại | Nút trên thẻ | Nhãn trạng thái |
|---|---|---|
| Máy lọc | Công tắc bật/tắt + nút Thấp · TB · Cao · Auto · Sleep | "Đang chạy: Lọc Cao" / "Đã tắt" |
| Cửa cuốn | Mở cửa · Dừng · Đóng cửa (luôn bấm được, nút đang hoạt động được tô sáng) | Đang mở / Đã đóng / Đang đóng... / Đã dừng / Mở một phần |
| Máy bơm (công tắc) | Công tắc bật/tắt | Đang chạy / Đã tắt / Mất kết nối |
| Máy cho ăn | Nhả 1 phần · Nhả 2 phần · Nhả 3 phần | Sẵn sàng • lần trước N phần / Đang nhả hạt... |

- Mỗi thẻ có nút **"Tạo icon xử lý nhanh"** (ghim shortcut ra màn hình chính).
- **Kéo-thả sắp xếp** bằng tay cầm ⋮⋮ bên phải thẻ (chỉ khi xem "Tất cả"); thứ tự **lưu theo tài khoản** (đăng nhập máy khác vẫn thấy đúng thứ tự), gửi lên máy chủ sau 2 giây kể từ lần kéo cuối, mất mạng thì tự thử lại. Kéo xuống làm mới để nhận thứ tự vừa sắp trên máy khác.
- Trạng thái **tự cập nhật 6 giây/lần** khi tab Home đang hiện và app ở foreground; tự dừng khi chuyển tab / app vào nền (tiết kiệm pin, mạng). Máy cho ăn chỉ đọc khi thẻ hiện và sau lệnh (tiết kiệm quota Tuya).
- Bấm nút → nút được **tô sáng ngay** (lạc quan), sau đó đọc lại trạng thái thật nhiều nhịp (~0,7 / 1,3 / 2 / 3 giây) và chỉ bỏ tô sáng khi thiết bị xác nhận đúng chế độ (hoặc quá ~10 giây). Chặn bấm đúp.
- Banner đỏ "Mất kết nối máy chủ. Đang thử lại..." khi mất mạng; lúc mở app hiện "Đang đánh thức máy chủ..." (chờ Render thức dậy, tối đa 35 giây).

### 4.4. Tab AI Assistant — `ai_assistant_tab.dart`

- Giao diện dạng **chat**: lời chào theo tên, bong bóng người dùng / trợ lý, mỗi kết quả kèm danh sách thiết bị + thành công/thất bại.
- **Nói bằng micro** (nhận dạng tiếng Việt `vi_VN`) hoặc **gõ chữ**.
- Cách chốt câu: ngừng nói **1,5 giây** → tự gửi; hoặc kết thúc câu bằng từ **"over"**. Câu gọi "Tom có nghe không" → trợ lý đáp "Tom đang nghe đây 🎙️".
- Bị từ chối quyền micro → giải thích + nút **Mở Cài đặt**.
- **Đọc to phản hồi** (TTS tiếng Việt), ví dụ "Đã tắt Máy bơm tăng áp"; tự dừng đọc khi bật mic. Tắt/bật ở Hồ sơ.
- Ví dụ câu lệnh:
  - Điều khiển ngay: "bật máy lọc mức cao", "tắt máy bơm", "đóng cửa cuốn", "cho mèo ăn 2 phần", "tắt hết".
  - Câu phức: "đóng cửa **và** tắt máy lọc".
  - Hẹn giờ: "6 giờ sáng mai bật máy bơm", "hẹn 16h30 bật quạt lọc mức cao", "từ 22 giờ đến 6 giờ bật máy lọc chế độ ngủ", "mỗi ngày 7 giờ tối đóng cửa".
  - Chạy kịch bản: "ra khỏi nhà" (kịch bản có mở cửa phải chạy trên màn hình, không chạy bằng giọng nói).
- Có kết nối WebSocket "Live" (hiện chỉ echo, giữ tối đa 200 tin).

### 4.5. Tab Hẹn giờ — `schedule_tab.dart`

**Danh sách lịch**
- Mỗi thẻ: giờ (lịch khoảng hiện "16:30 → 17:30", qua đêm thêm ⁺¹), tóm tắt hành động ("Lọc Cao → Lọc TB • tên lịch"), các ngày lặp, nhãn **"1 lần"** nếu lịch chạy một lần.
- **Công tắc** trên thẻ để tạm dừng / bật lại lịch.
- Chạm thẻ để **sửa**, nút xóa có hỏi xác nhận.
- Danh sách trống: "Chưa có lịch nào. Bấm ＋ để tạo lịch hẹn giờ đầu tiên."

**Form thêm/sửa** (bottom sheet, nút ＋)
1. **Thiết bị** (danh sách thiết bị mình được dùng).
2. **Loại lịch**: "Một mốc" hoặc "Khoảng".
3. **Hành động** theo loại thiết bị: máy lọc (Bật/Tắt/Lọc Thấp/TB/Cao/Auto/Ngủ), cửa (Mở/Đóng/Dừng), máy cho ăn (Nhả 1–3 phần), công tắc (Bật/Tắt).
4. **Giờ** (TimePicker).
5. *(Khoảng)* **Giờ kết thúc** + **Hành động kết thúc**. Giờ kết thúc trùng giờ bắt đầu → báo lỗi; nhỏ hơn → ghi chú "Kết thúc vào ngày hôm sau (lịch qua đêm)".
6. **Lặp lại**: chọn T2…CN (bỏ trống = mỗi ngày).
7. **Tên lịch** (tùy chọn).

### 4.6. Lịch sử điều khiển — `history_screen.dart`

- Mở từ menu tài khoản → "Lịch sử điều khiển".
- Nhóm theo **ngày**; mỗi dòng: thiết bị, lệnh, giờ, **ai bấm**, **bấm từ đâu**.
- Nguồn: App · Widget · Icon nhanh · Giọng nói · Kịch bản · Lịch hẹn · **App Smart Life** · **Tại thiết bị** (nút vật lý / công tắc tường / lịch cài trong máy) · Bên ngoài.
- Dòng có **⚠ đỏ** = thiết bị không nhận lệnh.
- **Chip lọc theo thiết bị**, công tắc **"Chỉ ngoài app"**, nút **"Tải thêm"**, nút tải lại.
- Chỉ hiện lịch sử của thiết bị mà người xem được dùng.

### 4.7. Hồ sơ & giao diện — `profile_screen.dart`

- **Tên hiển thị** (1–40 ký tự), **màu avatar** (chọn màu hoặc "Tự động").
- Xem vai và khu được cấp.
- **Giao diện**: Theo hệ thống / Sáng / Tối.
- **Trợ lý giọng nói**: bật/tắt "Đọc to phản hồi".
- **Tài khoản**: Đổi mật khẩu (bắt nhập mật khẩu hiện tại, mật khẩu mới nhập 2 lần).
- **Hướng dẫn sử dụng** — 10 mục: Điều khiển thiết bị · Nhà theo khu · Kịch bản · Hẹn giờ · Trợ lý giọng nói · Widget & icon nhanh · Lịch sử điều khiển · Hồ sơ/giao diện/mật khẩu · Quyền theo vai · Quản trị nhà (chỉ chủ nhà thấy). Nội dung nằm ở một chỗ duy nhất: `helpTopics` trong `help_screen.dart`.
- **Đăng xuất**.

### 4.8. Quản trị nhà (chỉ chủ nhà) — `admin_screen.dart`

**Tab Thành viên**
- Ô **tìm kiếm** theo tên/email, không phân biệt dấu tiếng Việt.
- Nhóm: **Chưa thuộc nhà** (ghim đầu) · **Trong nhà** · **Đã chặn**.
- Nút **"Thêm vào nhà"**: chọn vai + khu trong một bước.
- Chạm một thành viên: đổi **vai**, **trạng thái** (đưa ra khỏi nhà / chặn), tick **khu được dùng** (ẩn với chủ nhà/người lớn vì hai vai này thấy mọi khu).

**Tab Khu vực**
- **Thêm khu vực**, menu mỗi khu: **Đổi tên**, **Dùng chung cả nhà** (bật/tắt), **Xóa khu** (thiết bị về "Chưa phân khu", không bị xóa).
- Mỗi thiết bị trong khu: nút **"Chuyển khu"**; chạm dòng thiết bị → chọn **loại thiết bị** (Máy lọc / Cửa cuốn / Máy cho ăn / Công tắc / Tự đoán theo tên).
- Khu giả **"Chưa phân khu"** ghim cuối và mở sẵn — để thiết bị mới thêm không bị lãng quên.

### 4.9. Trình soạn kịch bản — `scene_editor_screen.dart`

- Đặt **tên** + chọn **icon**.
- **Thêm hành động**: chọn thiết bị (kèm tên khu) → chọn hành động theo loại.
- Danh sách "HÀNH ĐỘNG (chạy lần lượt từ trên xuống)", **kéo-thả** đổi thứ tự.
- Nút **Lưu**, nút **Xóa** (có xác nhận).

### 4.10. Ngoài màn hình chính điện thoại (Android)

**Home Screen Widget "Smart Home"** (`SmartHomeWidgetProvider.kt`, `widget_service.dart`)
- 3 khe cố định: **Máy lọc** (nút "Đổi mức") · **Cửa cuốn** (nút "Mở/Đóng") · **Máy cho ăn** (nút "Cho ăn"); khe không có thiết bị thì ẩn.
- Mỗi khe hiện tên + trạng thái sống; nút **"↻ Làm mới"**.
- Bấm nút chạy **nền**, không mở app; xong tự làm mới widget.
- Khi app đóng: tự làm mới khoảng **15 phút/lần** (WorkManager — mức tối thiểu Android cho phép).

**Icon xử lý nhanh (pinned shortcut)** (`shortcut_handler.dart`, `MainActivity.kt`)
- Tạo từ nút "Tạo icon xử lý nhanh" trên thẻ thiết bị.
- Hành vi khi bấm:
  - Máy lọc: **xoay vòng** Tắt → Bật → Lọc Thấp → TB → Cao → Auto → Ngủ → Tắt...
  - Cửa: **đảo chiều** theo trạng thái thật (đang đóng → mở, đang mở → đóng); hoặc nút Mở / Đóng riêng có hỏi xác nhận.
  - Máy cho ăn: hỏi xác nhận rồi nhả hạt.
- **Icon đổi theo trạng thái** (`ic_purifier_{off,on,low,med,high,auto,sleep}`, `ic_door_{open,closed}`, `ic_feeder`); khi app đang mở, icon được đồng bộ theo trạng thái thật mỗi 6 giây.

---

## 5. Phần Backend — xử lý phía máy chủ

### 5.1. Khởi động (lifespan) — `main.py`, `core/database.py`

1. **Khởi tạo DB** (bọc try/except, lỗi → chạy chế độ "degraded", không sập app):
   `create_all` → `run_startup_migrations` (thêm cột thiếu, chạy cả SQLite & Postgres) → `verify_schema` (báo rõ thiếu bảng/cột) → `enable_rls` (Postgres: bật RLS, không policy = chặn truy cập trực tiếp bằng key công khai) → `seed_defaults` (3 thiết bị gốc + khu "Nhà" khi DB rỗng, giữ nguyên id).
2. **Kết nối từng hãng** (Tuya, VeSync, Rojeco) — mỗi hãng bọc riêng, một hãng lỗi không ảnh hưởng hãng khác.
3. **Bật scheduler** — chỉ khi DB sẵn sàng.
4. Log rõ: đang dùng SQLite hay Postgres, xác thực 🔒 BẬT / 🔓 TẮT, thiếu secret nào.

`/health` **luôn trả 200** với `{status:"online", db:true|false}` để UptimeRobot phân biệt "app sống nhưng lỗi DB" với "app chết".

### 5.2. Xác thực — `core/auth.py`

- Verify JWT Supabase: **ES256/RS256** qua JWKS của project (cache khóa, kiểm `aud`, `iss`); **HS256** qua `SUPABASE_JWT_SECRET` (project kiểu cũ). Thuật toán khác / `alg: none` → 401.
- **App-token dài hạn** (`POST /api/auth/app-token`, `iss="smarthome-app"`, ký bằng `APP_TOKEN_SECRET`): dùng cho Home Widget & shortcut chạy ở isolate nền (nơi không có phiên Supabase). Thu hồi toàn bộ = đổi `APP_TOKEN_SECRET`. Token cấp lúc xác thực đang TẮT bị từ chối khi đã bật.
- **Tự suy bật/tắt**: không đặt `AUTH_DISABLED` → bật khi có `SUPABASE_URL` hoặc `SUPABASE_JWT_SECRET`; `AUTH_DISABLED=0` ép bật (fail closed).

### 5.3. Phân quyền — `core/household.py` (nơi DUY NHẤT quyết định quyền)

| Hàm | Dùng ở | Việc |
|---|---|---|
| `provision_member` | mọi request | Tạo `guest/pending` cho người mới; nâng `ADMIN_EMAILS` thành owner |
| `get_current_member` | mọi endpoint trừ `/api/me` | Chặn `pending` / `blocked` (403) |
| `device_query` | danh sách thiết bị, AI, lịch sử | Lọc thiết bị theo khu được cấp + khu dùng chung |
| `require_device_access` | điều khiển, trạng thái, tạo lịch | 403 nếu ngoài khu, 404 nếu không tồn tại |
| `schedule_query` | danh sách lịch | Lọc theo **thiết bị** thấy được (lịch là của cả nhà) |
| `require_schedule_write` | sửa/xóa lịch | Khách không được; trẻ em chỉ lịch của mình |
| `require_scene_write` | tạo/sửa/xóa kịch bản | Chỉ owner/adult |
| `require_owner` | thiết bị, khu, thành viên | Chỉ chủ nhà |

Vai và quyền đọc từ DB **mỗi request** (không nhét vào JWT).

### 5.4. Điều khiển thiết bị & trạng thái

- **Connector** (`services/*_connector.py`) kế thừa `base_connector.py` (`connect`, `turn_on`, `turn_off`, `set_mode`, `get_device_state`), đăng ký qua `connector_manager.device_manager`.
- Hãng thiết bị **lấy từ DB**, không tin hãng trong URL.
- Endpoint điều khiển trả `{status:"error"}` khi thiết bị không nhận lệnh; `action` khác on/off → 400.
- Gọi HTTP đồng bộ của Tuya/Rojeco chạy qua `asyncio.to_thread` (không chặn event loop); timeout 15 giây mọi call Tuya.
- **Cache trạng thái ~3 giây**; `?fresh=1` bỏ qua cache; **mọi đường điều khiển** (nút, AI, kịch bản, scheduler) đều xóa cache sau lệnh.
- **Tuya**:
  - Tự phân loại theo category Tuya (tra một lần, cache): công tắc (`tdq`, `kg`, `cz`...) → DP `switch_1`; **không bao giờ** gửi `control` tới công tắc. Tra loại lỗi → **không gửi lệnh**.
  - Cửa: đọc `shadow/properties` (có thời điểm DP) — ưu tiên vị trí thật → tình trạng thật → lệnh cuối (`control`): cũ hơn 30 giây → `open`/`closed`, mới hơn → `opening`/`closing`.
  - Tự chèn `stop` trước khi đảo chiều cửa.
- **VeSync** (pyvesync 3.4.2): đọc `state.*`, đặt mức qua `set_fan_speed` / `set_auto_mode` / `set_sleep_mode`.
- **Rojeco**: online/offline, `feed_state` (standby/feeding/done), `last_feed` từ DP `feed_report`.

### 5.5. Chuẩn hóa hành động — `services/device_actions.py`

`normalize_action(device, verb, mode)` là **danh sách trắng theo loại**, bắt buộc với mọi đường không qua UI (AI, lịch bằng giọng nói, kịch bản):

| Loại | Bật/Tắt | Chế độ hợp lệ |
|---|---|---|
| Máy lọc | ✅ | `1`, `2`, `3`, `auto`, `sleep` |
| Cửa cuốn | ❌ | `open`, `close`, `stop` |
| Máy cho ăn | ❌ | `1`…`10` |
| Công tắc / chưa rõ | ✅ | — |

### 5.6. Trợ lý giọng nói — `POST /api/ai/parse`

```
Câu nói
 ├─ Khớp TÊN KỊCH BẢN (tên dài nhất thắng, câu không có giờ) → chạy kịch bản (từ chối nếu mở cửa)
 ├─ Không có từ khóa thiết bị / "hẹn" / "lịch" → trả rỗng (không gọi AI, tiết kiệm chi phí)
 ├─ Câu đơn → local_parser (miễn phí, nhanh)
 └─ Câu phức ("và", "rồi", "với", "nhưng") hoặc local không hiểu → ai_parser (OpenRouter)
        ↓
 Với mỗi hành động:
   • chỉ chạm thiết bị trong device_query của người nói (id AI trả về KHÔNG được tin)
   • intent "schedule" → TẠO LỊCH (không thi hành ngay)
   • còn lại → normalize_action → connector → ghi lịch sử (source=voice)
```

- **Parse giờ tiếng Việt** (`services/vn_time_parser.py`): "16 giờ 30", "16h30", "16:30", "X giờ rưỡi", "bảy giờ", buổi sáng/trưa/chiều/tối/đêm, "mai", "mỗi ngày / hàng ngày", "từ X đến Y" (qua đêm được).
- Câu có giờ → **chỉ tạo lịch**, tuyệt đối không bật luôn. Ngày đích được ghim + `one_shot` (giờ đã qua → tự hiểu ngày mai); "mỗi ngày" → lặp, không one-shot.
- Khoảng không nói hành động kết thúc → mặc định **Tắt**; cửa mở → đóng; cửa đóng/dừng → **không đoán** (lịch đơn).
- **"Tắt hết"** chỉ tắt máy lọc + công tắc; **"bật hết"** không đoán.
- Khách không tạo lịch bằng giọng nói (cùng luật với API).
- Thiếu `OPENROUTER_API_KEY` → app vẫn chạy, chỉ mất nhánh AI.

### 5.7. Hẹn giờ — `services/scheduler.py`

- Vòng lặp asyncio **tick 30 giây**, múi giờ **Asia/Ho_Chi_Minh**, cửa sổ ân hạn **120 giây**.
- Mốc bắn khi đúng thứ (hoặc mỗi ngày) + trong cửa sổ + chưa bắn hôm nay. **Đánh dấu đã bắn TRƯỚC khi gửi lệnh** → lệnh lỗi không bắn lặp (an toàn cho motor cửa).
- **Lịch khoảng**: start và end bắn **độc lập** (restart giữa khoảng vẫn trả thiết bị về trạng thái sau); qua đêm → ngày của end dịch +1.
- **One-shot**: lịch đơn tắt sau start, lịch khoảng tắt sau end; lỡ trọn cửa sổ (server ngủ) → tự tắt + log (không bắn nhầm tuần sau).
- Sửa giờ / bật lại → reset ngày đã bắn tương ứng; chỉ đổi tên thì không.
- `POST /api/schedules/{id}/run` (`?part=end`) chạy thử ngay, không đổi ngày đã bắn.

### 5.8. Kịch bản — `/api/scenes`

- Kịch bản của **cả nhà** (không gắn khu), hành động lưu dạng JSON đã chuẩn hóa (sai loại → 400).
- Chạy **tuần tự** (tránh lệnh chen nhau làm rối cơ chế khóa liên động của cửa).
- Hành động trên thiết bị ngoài khu người chạy → **bỏ qua** (`skipped`), báo trong kết quả.

### 5.9. Lịch sử điều khiển — `services/command_log.py`, `services/device_history.py`

- **Ghi mọi lệnh hệ thống gửi** sau khi connector trả kết quả: người (ảnh chụp tên lúc ghi), nguồn, hành động, thành công/thất bại. Lỗi DB khi ghi chỉ log, **không bao giờ làm hỏng lệnh**.
- Nguồn do client khai qua `?via=` chỉ nhận `app` / `widget` / `shortcut` (không giả được `schedule`...).
- **Sự kiện ngoài app**:
  - Tuya/Rojeco: kéo nhật ký `/v1.0/devices/{id}/logs` (type 5 = lệnh, type 7 = thiết bị báo) khi mở màn lịch sử; mỗi thiết bị ≤1 lần/60 giây, chờ tối đa 10 giây, nhìn lại 7 ngày, chống trùng bằng `ext_id`. `cloud2cloud` = chính backend (bỏ), `2` = app Smart Life, không có lệnh trước đó = tại thiết bị.
  - VeSync: không có nhật ký → so trạng thái giữa các lần đọc; đổi mà hệ thống không gửi lệnh trong 60 giây → "Bên ngoài".
- Giữ **90 ngày**.

### 5.10. Hồ sơ, khu vực, thành viên, thiết bị

- `PATCH /api/me`: sửa tên (1–40 ký tự) + màu avatar (`#RRGGBB` hoặc null) của chính mình.
- Khu vực: CRUD, `is_shared`; xóa khu → thiết bị về "Chưa phân khu".
- Thành viên: duyệt, đổi vai, chặn, cấp khu (`zone_ids` thay cả bộ).
- Thiết bị: thêm (idempotent — id trùng không lỗi), đổi tên / gán khu / đặt loại, xóa (**xóa luôn mọi lịch** của thiết bị để không có lịch mồ côi).

---

## 6. Danh sách API

| Method | Path | Ai dùng được | Mô tả |
|---|---|---|---|
| GET/HEAD | `/`, `/health` | Công khai | Health check, luôn 200, kèm `db` |
| POST | `/api/auth/app-token` | Đã đăng nhập, active | Cấp token dài hạn cho widget/shortcut |
| GET | `/api/me` | Mọi tài khoản (cả pending) | Vai, trạng thái, khu được cấp, thứ tự thiết bị (`sort_order`) |
| PATCH | `/api/me` | Active/pending | Sửa tên, màu avatar, thứ tự thiết bị (`sort_order`) của mình — chỉ trường có gửi mới đổi |
| GET | `/api/devices` | Active | Thiết bị đã lọc theo khu (+ `zone_id`, `zone_name`, `category`) |
| POST | `/api/devices` | Chủ nhà | Thêm thiết bị (idempotent) |
| PATCH | `/api/devices/{id}` | Chủ nhà | Đổi tên / khu / loại |
| DELETE | `/api/devices/{id}` | Chủ nhà | Xóa thiết bị + lịch của nó |
| GET | `/api/test-control/{brand}/{id}?action=on\|off&via=` | Có quyền thiết bị | Bật/tắt |
| GET | `/api/test-control/{brand}/{id}/mode?mode=&via=` | Có quyền thiết bị | Đổi chế độ (open/close/stop, 1/2/3/auto/sleep, số phần) |
| GET | `/api/devices/{brand}/{id}/status?fresh=1` | Có quyền thiết bị | Trạng thái sống |
| POST | `/api/ai/parse` | Active | Hiểu + thực thi câu lệnh tự nhiên |
| GET / POST | `/api/schedules` | Active / trừ khách | Liệt kê / tạo lịch |
| PATCH / DELETE | `/api/schedules/{id}` | Theo `require_schedule_write` | Sửa / xóa lịch |
| POST | `/api/schedules/{id}/run?part=end` | Theo `require_schedule_write` | Chạy thử lịch |
| GET / POST | `/api/scenes` | Active / owner+adult | Liệt kê / tạo kịch bản |
| PATCH / DELETE | `/api/scenes/{id}` | Owner, adult | Sửa / xóa kịch bản |
| POST | `/api/scenes/{id}/run` | Active | Chạy kịch bản |
| GET | `/api/history?limit&before_ms&device_id&sync` | Active | Lịch sử (chỉ thiết bị thấy được) |
| GET / POST | `/api/zones` | Active / chủ nhà | Liệt kê / tạo khu |
| PATCH / DELETE | `/api/zones/{id}` | Chủ nhà | Sửa / xóa khu |
| GET | `/api/members` | Chủ nhà | Danh sách thành viên |
| PATCH | `/api/members/{user_id}` | Chủ nhà | Duyệt / đổi vai / trạng thái / cấp khu |
| WS | `/ws` | — | WebSocket (hiện chỉ echo) |

---

## 7. Cơ sở dữ liệu

| Bảng | Nội dung chính | Ghi chú |
|---|---|---|
| `devices` | `id` (= id thật của hãng, PK), `name`, `brand`, `is_active`, `zone_id`, `category` | ⚠️ Không đổi PK — shortcut đã ghim, widget, lịch đều tham chiếu id này |
| `zones` | `id`, `name`, `sort_order`, `is_shared` | Xóa khu → `devices.zone_id` = NULL |
| `members` | `user_id` (= Supabase user id), `email`, `display_name`, `avatar_color`, `role`, `status`, `sort_order` (JSONB) | `sort_order` = thứ tự thiết bị Dashboard của từng người, lọc theo quyền khi đọc |
| `member_zone_access` | `(user_id, zone_id)` | Chỉ cho kid/guest |
| `schedules` | `name`, `brand`, `device_id`, `action_type/value`, `time`, `days`, `enabled`, `last_fired_date`, `end_time`, `end_action_type/value`, `last_end_fired_date`, `one_shot`, `created_by` | `days` CSV 0=T2…6=CN, rỗng = mỗi ngày |
| `scenes` | `name`, `icon`, `sort_order`, `actions` (JSON), `created_by` | |
| `command_logs` | `at_ms`, `device_id`, `device_name`, `user_name`, `action_*`, `source`, `user_id`, `success`, `detail`, `ext_id` (UNIQUE) | Giữ 90 ngày |

- Production: **Postgres Supabase (Tokyo)** qua Session pooler (IPv4, port 5432). Dev: SQLite `backend/smarthome.db`.
- Schema Postgres: `backend/docs/supabase_schema.sql`; hướng dẫn: `backend/docs/SUPABASE_SETUP.md`.

---

## 8. Các luồng hoạt động chính

**Bấm nút trên app**
```
Thẻ thiết bị → tô sáng ngay → DeviceApi.sendMode(via=app)
 → /api/test-control/... → kiểm quyền → connector → xóa cache → ghi lịch sử
 → app đọc lại /status?fresh=1 nhiều nhịp → bỏ tô sáng khi thiết bị xác nhận
```

**Bấm nút trên Home Widget (app đang đóng)**
```
Nút widget → isolate nền → đọc app-token (SharedPreferences) → gọi API (via=widget)
 → làm mới 3 khe widget
```

**Ra lệnh giọng nói**
```
Micro → nhận dạng vi_VN → im 1,5s → POST /api/ai/parse
 → kịch bản? / local parser / AI → normalize_action → connector (hoặc tạo lịch)
 → bong bóng kết quả + đọc to
```

**Lịch hẹn tới giờ**
```
scheduler tick 30s → lịch đến giờ → đánh dấu đã bắn → connector → xóa cache
 → ghi lịch sử (source=schedule) → one-shot thì tự tắt
```

**Người mới vào nhà**
```
Đăng ký trong app → pending (màn "Chưa thuộc nhà nào")
 → Chủ nhà: Quản trị → Thành viên → tìm → "Thêm vào nhà" (vai + khu)
 → người mới bấm "Kiểm tra lại" → vào app
```

---

## 9. An toàn lệnh & bảo mật

- **Cửa cuốn không nhận bật/tắt** — "bật tất cả" không thể thành mở cửa.
- **Kịch bản mở cửa**: app hỏi xác nhận; giọng nói **từ chối** (nhận dạng có thể nghe nhầm).
- **AI không được tin**: id thiết bị AI trả về phải nằm trong danh sách người nói được thấy; hãng lấy từ DB.
- **Tuya không rõ loại → không gửi lệnh** (từng có lỗi coi máy bơm là cửa và gửi `control:open`).
- Lịch: đánh dấu đã bắn trước khi gửi → không bắn lặp.
- Supabase **publishable key nằm trong APK** → không phải bí mật; an toàn đến từ RLS deny-all + bước chủ nhà duyệt thành viên.
- Credential chỉ ở biến môi trường (`backend/.env`, Render Dashboard): `VESYNC_*`, `TUYA_*`, `OPENROUTER_API_KEY`, `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_JWT_SECRET`, `ADMIN_EMAILS`, `APP_TOKEN_SECRET`, `AUTH_DISABLED`.
- Test backend dùng fixture giả — **không test nào gửi lệnh tới thiết bị thật**.

---

## 10. Vận hành & triển khai

- **Backend**: Render free tier; `render.yaml` ghim `rootDir: backend`, `healthCheckPath: /health`, `PYTHON_VERSION=3.13.5`. ⚠️ Service tạo tay không đọc `render.yaml` — biến môi trường set trong Dashboard.
- **Requirements**: `backend/requirements.txt` là danh sách thật; `requirements.txt` ở gốc chỉ là con trỏ `-r backend/requirements.txt` (không xóa).
- **Giữ server thức**: UptimeRobot ping `/health`.
- **Nhánh**: làm việc trên `release/prod-ready`; `main` chỉ **fast-forward** (từng có commit revert Phase 0 — merge thẳng sẽ áp lại revert).
- **APK**: `flutter build apk --release --dart-define-from-file=supabase.json` (khóa ở `frontend/supabase.json`, gitignore).
- **Lệnh hay dùng**:
  ```bash
  cd backend && uvicorn app.main:app --reload
  cd backend && pytest
  cd frontend && flutter run
  cd frontend && dart analyze && flutter test
  ```

---

## 11. Giới hạn đã biết

- **Remote RF cửa cuốn** điều khiển thẳng motor → cloud không biết: trạng thái cửa có thể sai và lịch sử không ghi được (cần cảm biến cửa).
- Cửa nhà hiện chỉ có DP `control` → không có **vị trí thật**, trạng thái suy từ lệnh cuối + thời gian hành trình 30 giây.
- **Shortcut ghim** là ảnh tĩnh, chỉ đổi icon khi app đang chạy.
- **Widget** chỉ hiện 1 thiết bị mỗi loại; làm mới nền tối thiểu 15 phút.
- **VeSync**: thay đổi ngoài app chỉ phát hiện khi có người mở app; giờ ghi là lúc phát hiện.
- Máy cho ăn **không báo** mức hạt / pin.
- Server Render free có thể ngủ nếu UptimeRobot gián đoạn → lịch trễ, app chờ "đánh thức".
- SQLAlchemy đồng bộ chạy trên event loop (mỗi query tới Supabase Tokyo chặn loop); race nhỏ ở cache trạng thái 3 giây.
- WebSocket `/ws` mới chỉ echo.
- Thứ tự thiết bị: hai máy cùng tài khoản sắp xếp gần như cùng lúc thì bản lưu sau thắng; máy kia chỉ thấy thứ tự mới khi mở lại app hoặc kéo xuống làm mới.

---

## 12. Bảng tổng hợp trạng thái tính năng

| # | Tính năng | Backend | UI | Trạng thái |
|---|---|---|---|---|
| 1 | Quản lý thiết bị (thêm / sửa / xóa / gán khu / đặt loại) | `/api/devices` | Quản trị → Khu vực | ✅ |
| 2 | Điều khiển bật/tắt & chế độ | `/api/test-control` + connectors | Thẻ thiết bị | ✅ |
| 3 | Trạng thái sống thiết bị | `/status` + cache 3s | Nhãn trạng thái, poll 6s | ✅ |
| 4 | Trợ lý giọng nói (local + AI) | `/api/ai/parse` | Tab AI Assistant | ✅ |
| 5 | Tạo lịch bằng giọng nói | `vn_time_parser` | Tab AI Assistant | ✅ |
| 6 | Đọc to phản hồi (TTS) | — | `voice_feedback.dart` | ✅ |
| 7 | Hẹn giờ đơn / khoảng / qua đêm / một lần | `scheduler.py`, `/api/schedules` | Tab Hẹn giờ | ✅ |
| 8 | Kịch bản (1 nút nhiều thiết bị) | `/api/scenes` | Hàng kịch bản, trình soạn | ✅ |
| 9 | Khu vực + khu dùng chung + lọc theo khu | `/api/zones`, `household.py` | Chip lọc, Quản trị | ✅ |
| 10 | Thành viên & phân quyền theo vai | `/api/members`, `household.py` | Quản trị → Thành viên | ✅ |
| 11 | Đăng nhập / đăng ký (Supabase) | `auth.py` | AuthGate, Login | ✅ đã bật trên production |
| 12 | Quên mật khẩu (OTP) / đổi mật khẩu | Supabase | Quên mật khẩu, Hồ sơ | ✅ |
| 13 | Hồ sơ cá nhân (tên, màu avatar) | `PATCH /api/me` | Hồ sơ | ✅ |
| 14 | Giao diện Sáng / Tối | — | Hồ sơ | ✅ |
| 15 | Lịch sử điều khiển (gồm ngoài app) | `/api/history`, `device_history.py` | Lịch sử điều khiển | ✅ |
| 16 | Home Screen Widget | dùng API chung + app-token | Widget Android | ✅ |
| 17 | Icon xử lý nhanh (shortcut) | dùng API chung + app-token | Shortcut Android | ✅ |
| 18 | Sắp xếp thiết bị kéo-thả (đồng bộ theo tài khoản) | `members.sort_order`, `PATCH /api/me` | Tab Home | ✅ |
| 19 | Hướng dẫn sử dụng + giới thiệu lần đầu | — | Hồ sơ → Hướng dẫn, Onboarding | ✅ |
| 20 | Lưu dữ liệu bền (Postgres Supabase) | `database.py` | — | ✅ |
| 21 | Automation engine (luật tự động) | `automation_engine.py` | — | 📋 Đóng băng |
| 22 | WebSocket thời gian thực | `/ws` (echo) | Chỉ báo "Live" | 🚧 Chưa dùng thật |
