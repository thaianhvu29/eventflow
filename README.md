# EventFlow — Website đặt vé sự kiện

Ứng dụng Flask có giao diện tiếng Việt, PostgreSQL, Docker Compose và các endpoint chuẩn bị cho đề tài CI/CD, giám sát và cảnh báo.

## Chức năng đã có

- Sáu sự kiện mẫu, poster SVG đi kèm; không phụ thuộc CDN hay ảnh bên ngoài.
- Tìm kiếm không dấu, lọc danh mục và thành phố, giao diện responsive.
- Trang chi tiết, chọn số lượng, đặt vé và nhận mã xác nhận.
- Tra cứu bằng mã vé + email; không có API liệt kê công khai dữ liệu khách hàng.
- Lưu đơn và giảm tồn vé trong cùng một transaction. UPDATE có điều kiện ngăn bán vượt tồn.
- Chống gửi lặp bằng request key; xác thực CSRF cho các POST từ trình duyệt.
- Giá tính trên server, kiểm tra email/số lượng, không bán sự kiện đã diễn ra.
- Health check, metrics và phiên bản ứng dụng.

Đây là bản nền phục vụ đồ án. Thanh toán được mô phỏng; không thu tiền thật, không gửi email và không có đăng nhập/quản trị. Người dùng phải lưu mã đặt vé. Năm sự kiện mẫu là 2027, múi giờ lịch sự kiện là Việt Nam (UTC+7). Seed chỉ chạy khi bảng sự kiện trống và không tự xóa đơn.

## Chạy trên server bằng Docker Compose

Yêu cầu: Docker Engine và Compose plugin (`docker compose version`). Giải nén rồi vào thư mục `eventflow`.

```bash
cp .env.example .env
python3 -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_hex(24)); print('SECRET_KEY=' + secrets.token_hex(32))"
nano .env
```

Dán hai giá trị vừa tạo vào `.env`, thay cho giá trị mẫu. Giữ password dạng hex để không cần URL-encode trong DATABASE_URL. Không commit `.env`.

Mặc định ứng dụng chỉ lắng nghe trên `127.0.0.1:8080`. Nếu truy cập từ máy cá nhân vào server, có thể giữ mặc định và dùng SSH tunnel:

```bash
ssh -L 8080:127.0.0.1:8080 USER@SERVER_IP
```

Hoặc sửa `BIND_ADDRESS=0.0.0.0` trong `.env` để mở cổng trên server; cấu hình firewall/security group cho cổng 8080 chỉ từ IP cần truy cập. Khi đó mở `http://SERVER_IP:8080`.

```bash
docker compose up -d --build
docker compose ps -a
docker compose logs --tail=100 web init
curl -f http://127.0.0.1:8080/health/ready
```

`init` chạy tạo bảng/seed rồi thoát mã 0 là bình thường. `web` chờ `init` thành công mới chạy. PostgreSQL không mở cổng ra host. Database lưu trong named volume `pgdata`.

Dừng mà giữ dữ liệu:

```bash
docker compose down
```

Không thêm `-v` nếu muốn giữ dữ liệu. Đổi POSTGRES_PASSWORD sau khi đã tạo volume không tự đổi mật khẩu database hiện có.

Khi cần triển khai lại mã nguồn:

```bash
docker compose up -d --build
```

## Chạy không dùng Docker để phát triển

Python 3.12 được khuyến nghị. SQLite được dùng khi không có DATABASE_URL, phù hợp chạy thử; Docker dùng PostgreSQL.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
flask --app app:create_app init-db
flask --app app:create_app run --host 127.0.0.1 --port 8000
```

Mở `http://127.0.0.1:8000`. Flask development server chỉ dành cho phát triển; Docker dùng Gunicorn.

## Kiểm thử

```bash
python -m pytest -q
```

Tests dùng SQLite tạm riêng biệt. Có kiểm tra đặt vé, giá server, gửi lặp, tra cứu sai email, CSRF, số lượng không hợp lệ, hết vé, sự kiện quá hạn, readiness và tranh mua 3 vé cuối. Cần chạy lại kiểm thử đồng thời trên PostgreSQL/server thật khi làm thử tải; kết quả SQLite không thay thế phép đo PostgreSQL.

## Endpoint phục vụ đề tài

| Endpoint | Mục đích |
| --- | --- |
| `/health/live` | Tiến trình hoạt động, trả phiên bản |
| `/health/ready` | Database kết nối được và có bảng sự kiện |
| `/metrics` | Prometheus exposition |
| `/api/bookings` | POST đặt vé (CSRF bắt buộc) |
| `/api/tickets/lookup` | POST tra cứu (CSRF bắt buộc) |

Metrics chính: `eventflow_http_requests_total`, `eventflow_http_request_duration_seconds`, `eventflow_booking_results_total`. Route được nhóm theo mẫu, không dùng email/mã vé làm label. `/metrics` hiện đi cùng cổng ứng dụng; khi thêm Nginx cần chỉ cho máy giám sát truy cập endpoint này. Chỉ dùng 1 Gunicorn worker trong cấu hình hiện tại để metrics trong bộ nhớ nhất quán; metrics reset khi restart. Nếu tăng worker, cần cấu hình Prometheus multiprocess đúng cách.

## Cấu trúc

```text
app.py               Flask routes, models, transaction và metrics
templates/           Giao diện Jinja
static/              CSS, JavaScript, poster SVG
tests/              Kiểm thử nghiệp vụ và tích hợp SQLite
Dockerfile           Build ứng dụng bằng Gunicorn
compose.yaml         Web + PostgreSQL + init
.env.example         Cấu hình mẫu
```

## Bước tiếp theo của đề tài

1. Đưa code lên Git, chạy bộ test trong CI.
2. Build image có tag commit SHA và đẩy registry.
3. Thêm deploy script, readiness verification và rollback image.
4. Kết nối Prometheus/Grafana/Alertmanager, bổ sung dashboard và cảnh báo.
5. Thử tải bằng k6, đo thời gian phát hiện lỗi và khôi phục.

Những mục trên chưa được triển khai trong gói này. Bản hiện tại tập trung hoàn thiện web và backend như yêu cầu.

Trước khi phục vụ người dùng thật: thêm HTTPS (sau đó COOKIE_SECURE=true), rate limit ở reverse proxy, quản lý danh tính/quyền quản trị, quy trình thanh toán và backup database. `db.create_all()` không quản lý migration cho những lần đổi schema sau này; dùng migration khi phát triển schema.

## Kết quả kiểm tra trong môi trường tạo mã

13 tests đã đạt với SQLite; JavaScript vượt kiểm tra cú pháp `node --check`. Docker, PostgreSQL và kiểm tra trực quan bằng trình duyệt chưa chạy được trong môi trường này. Cần xác nhận trên server đích trước khi dùng cho demo chính thức.
