# Chuyển DB sang Supabase Postgres (Phase 1a)

Làm một lần, khoảng 15 phút. Sau bước này lịch hẹn không còn bị mất mỗi lần deploy.

## Vì sao phải làm

Ổ đĩa của Render free là **ephemeral**: mỗi lần deploy, container được dựng lại
từ repo. File `backend/smarthome.db` đang được track trong git, nên nó bị ghi đè
bằng bản chụp trong repo — bảng `schedules` rỗng. Kết quả: **mọi lịch hẹn người
dùng đã tạo đều biến mất sau mỗi lần deploy**, kể cả deploy không liên quan gì
đến lịch.

Postgres nằm ngoài container nên không bị ảnh hưởng.

Phase 1a **chỉ đổi chỗ lưu dữ liệu**. Không thêm đăng nhập, không thêm phân
quyền, app trên điện thoại không cần build lại.

---

## Bước 1 — Tạo project Supabase

1. Vào https://supabase.com → **New project**
2. Điền:
   - **Name**: `smarthome`
   - **Database Password**: bấm Generate, rồi **lưu ngay vào trình quản lý mật
     khẩu**. Supabase không cho xem lại; mất thì phải reset.
   - **Region**: `Southeast Asia (Singapore)` — gần Việt Nam nhất, và Render
     của dự án cũng ở Singapore.
3. Bấm **Create new project**, chờ ~2 phút.

## Bước 2 — Tạo bảng

1. Trong project, mở **SQL Editor** (thanh bên trái) → **New query**
2. Mở file [`supabase_schema.sql`](./supabase_schema.sql) trong repo, copy **toàn
   bộ** nội dung, dán vào editor
3. Bấm **Run**

Kiểm tra: mở **Table Editor**, phải thấy 2 bảng `devices` và `schedules`, trong
đó `devices` có sẵn 3 dòng (Cửa cuốn, Lọc không khí Core 300S, Máy cho mèo ăn).

File này chạy lại nhiều lần cũng không sao — nó không ghi đè dữ liệu đã có.

## Bước 3 — Lấy connection string

⚠️ **Đây là bước dễ sai nhất.** Phải lấy đúng loại, nếu không Render sẽ không
kết nối được và lỗi báo rất mơ hồ.

1. **Project Settings** (bánh răng) → **Database**
2. Kéo tới mục **Connection string** → chọn tab **Session pooler**

   Lý do phải là pooler, không phải Direct connection: kết nối trực tiếp của
   Supabase **chỉ có IPv6**, mà Render free **không có IPv6** → sẽ lỗi
   `Network is unreachable`. Pooler có IPv4.

   Trong hai loại pooler, chọn **Session** (port `5432`), không phải Transaction
   (port `6543`) — SQLAlchemy giữ sẵn một pool kết nối, hợp với session mode.

3. Copy chuỗi, dạng như:

   ```
   postgresql://postgres.abcdefghijklm:[YOUR-PASSWORD]@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres
   ```

4. Thay `[YOUR-PASSWORD]` bằng mật khẩu đã lưu ở Bước 1.

   ⚠️ Nếu mật khẩu có ký tự đặc biệt (`@ : / ? # [ ] %`) thì phải **URL-encode**
   nó, nếu không chuỗi bị cắt sai chỗ. Ví dụ `p@ss` → `p%40ss`. Cách tránh phiền:
   reset mật khẩu thành chuỗi chỉ gồm chữ và số.

## Bước 4 — Đặt biến môi trường trên Render

1. Render Dashboard → service `vuhp-smarthome` → tab **Environment**
2. **Add Environment Variable**:
   - Key: `DATABASE_URL`
   - Value: chuỗi vừa dựng ở Bước 3
3. **Save Changes** — Render sẽ tự deploy lại.

> Đừng commit chuỗi này vào git. Nó chứa mật khẩu DB.
> Ở local, nếu muốn test với Postgres thì đặt `DATABASE_URL` trong `backend/.env`.
> Không đặt thì code tự động fallback về SQLite như cũ.

## Bước 5 — Kiểm tra

```bash
curl https://vuhp-smarthome.onrender.com/health
# mong đợi: {"status":"online","db":true}

curl https://vuhp-smarthome.onrender.com/api/devices
# mong đợi: đủ 3 thiết bị
```

Trong **Logs** của Render phải thấy:

```
Đang khởi tạo Database (Postgres)...
✅ Database sẵn sàng.
```

Nếu vẫn thấy `(SQLite)` kèm dòng cảnh báo màu vàng thì `DATABASE_URL` chưa được
đọc — kiểm tra lại tên biến có gõ đúng không.

### Phép thử thật sự (chứng minh đã hết lỗi mất dữ liệu)

1. Mở app, tạo một lịch hẹn bất kỳ
2. Vào Render Dashboard bấm **Manual Deploy** → **Deploy latest commit**
3. Chờ deploy xong, mở lại app

Lịch **vẫn còn**. Trước Phase 1a thì bước này làm nó biến mất.

---

## Khi có sự cố

| Triệu chứng trong log Render | Nguyên nhân | Cách sửa |
|---|---|---|
| `Network is unreachable` | Dùng Direct connection (IPv6), Render free không có IPv6 | Quay lại Bước 3, lấy chuỗi **Session pooler** |
| `password authentication failed` | Sai mật khẩu, hoặc ký tự đặc biệt chưa URL-encode | Reset mật khẩu DB thành chữ + số, dựng lại chuỗi |
| `could not translate host name` | Chuỗi bị cắt/thiếu do dán sót | Copy lại nguyên chuỗi |
| `Schema DB không khớp với code` | Chưa chạy `supabase_schema.sql` | Làm lại Bước 2 |
| `/health` trả `db:false` | Bất kỳ lỗi nào ở trên | Đọc dòng log ngay phía trên, nó ghi rõ nguyên nhân |

App được thiết kế để **không sập** khi DB lỗi: `/health` vẫn trả 200 với
`db:false`, scheduler không chạy, UptimeRobot không báo động nhầm. Nhưng điều
khiển thiết bị vẫn hoạt động bình thường vì nó gọi thẳng cloud của hãng.

## Sau khi chạy ổn định

Có thể gỡ file SQLite khỏi git — nó không còn được dùng trên production và chỉ
gây nhầm lẫn. Việc này để ở Phase 5, không làm vội:

```bash
git rm --cached backend/smarthome.db
```
