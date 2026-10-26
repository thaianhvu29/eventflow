import os
import re
import secrets
import time
from datetime import datetime, timezone, timedelta

import click
from flask import Flask, abort, g, jsonify, render_template, request, session
from flask_sqlalchemy import SQLAlchemy
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import CheckConstraint, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


db = SQLAlchemy()
REQUESTS = Counter('eventflow_http_requests_total', 'HTTP requests', ['method', 'route', 'status'])
LATENCY = Histogram('eventflow_http_request_duration_seconds', 'HTTP latency', ['route'])
BOOKINGS = Counter('eventflow_booking_results_total', 'Booking outcomes', ['result'])


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    category = db.Column(db.String(40), nullable=False)
    city = db.Column(db.String(60), nullable=False)
    venue = db.Column(db.String(180), nullable=False)
    starts_at = db.Column(db.DateTime(timezone=False), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    remaining = db.Column(db.Integer, nullable=False)
    theme = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text, nullable=False)
    __table_args__ = (CheckConstraint('remaining >= 0 AND remaining <= capacity'), CheckConstraint('price >= 0'))


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False)
    request_key = db.Column(db.String(64), unique=True, nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(254), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    event = db.relationship(Event)
    __table_args__ = (CheckConstraint('quantity > 0 AND quantity <= 10'),)


def seed_events():
    if db.session.scalar(select(Event.id).limit(1)):
        return
    items = [
        ('Đà Nẵng Indie Night', 'Âm nhạc', 'Đà Nẵng', 'Công viên Biển Đông', '2027-03-20T18:30:00+07:00', 350000, 300, 'music', 'Một đêm nhạc bên biển, nơi những giai điệu indie gặp gỡ ánh hoàng hôn. Cùng những nghệ sĩ trẻ và ban nhạc độc lập, tận hưởng không gian mở đầy cảm hứng. Vé bao gồm vào cửa và một phần nước uống.'),
        ('Build Something Great', 'Công nghệ', 'Đà Nẵng', 'Không gian sáng tạo • Hải Châu', '2027-03-27T08:30:00+07:00', 150000, 100, 'tech', 'Workshop thực hành dành cho những người thích biến ý tưởng thành sản phẩm. Gặp gỡ cộng đồng lập trình, cùng xây một ứng dụng nhỏ và chia sẻ cách làm việc hiệu quả. Vui lòng mang theo laptop.'),
        ('Một chiều làm gốm', 'Workshop', 'Hội An', 'Xưởng Mộc • Cẩm Châu', '2027-04-03T14:00:00+07:00', 280000, 24, 'craft', 'Chậm lại một chút và tự tay tạo nên chiếc cốc của riêng bạn. Người hướng dẫn sẽ đồng hành từ bước tạo hình đến trang trí. Giá vé bao gồm vật liệu, nung sản phẩm và trà.'),
        ('Sunrise Run 2027', 'Thể thao', 'Đà Nẵng', 'Công viên Châu Á', '2027-04-11T05:30:00+07:00', 200000, 500, 'run', 'Bắt đầu ngày mới với đường chạy 5 km đầy năng lượng. Phù hợp với người mới bắt đầu và các nhóm bạn. Vé bao gồm số đeo, nước uống và huy chương hoàn thành.'),
        ('Chạm vào sắc màu', 'Nghệ thuật', 'Huế', 'Nhà triển lãm • Lê Lợi', '2027-04-17T09:00:00+07:00', 120000, 80, 'art', 'Khám phá triển lãm tranh đương đại từ các tác giả trẻ miền Trung. Một không gian để nhìn, cảm nhận và trò chuyện về nghệ thuật. Vé có giá trị một lượt vào cửa trong ngày.'),
        ('Coffee & Conversations', 'Workshop', 'Đà Nẵng', 'The Corner • Sơn Trà', '2027-04-24T09:00:00+07:00', 180000, 40, 'coffee', 'Một buổi sáng dành cho cà phê và những cuộc trò chuyện mới. Tìm hiểu cách pha pour-over, nếm thử ba loại hạt và kết nối cùng những người chung sở thích. Không cần kinh nghiệm trước đó.'),
    ]
    for title, category, city, venue, starts, price, capacity, theme, description in items:
        db.session.add(Event(title=title, category=category, city=city, venue=venue, starts_at=datetime.fromisoformat(starts).replace(tzinfo=None), price=price, capacity=capacity, remaining=capacity, theme=theme, description=description))
    db.session.commit()


def create_app(test_config=None):
    app = Flask(__name__)
    secret = os.environ.get('SECRET_KEY')
    if not secret and not test_config:
        raise RuntimeError('Set SECRET_KEY before starting EventFlow. See README.md.')
    app.config.update(SECRET_KEY=secret or 'test-only', SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL', 'sqlite:///eventflow.db'), SQLALCHEMY_TRACK_MODIFICATIONS=False, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE', 'false').lower() == 'true', MAX_CONTENT_LENGTH=16384)
    if test_config:
        app.config.update(test_config)
    db.init_app(app)

    @app.template_filter('vnd')
    def vnd(value):
        return f'{value:,}'.replace(',', '.') + 'đ'

    @app.context_processor
    def context():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(32)
        return {'csrf_token': session['csrf'], 'version': os.environ.get('APP_VERSION', '1.0.0')}

    @app.before_request
    def before_request():
        g.started = time.monotonic()
        if request.method == 'POST':
            supplied = request.headers.get('X-CSRF-Token', '')
            expected = session.get('csrf', '')
            if not expected or not secrets.compare_digest(supplied, expected):
                return jsonify(error='Phiên làm việc đã hết hạn. Vui lòng tải lại trang.'), 403

    @app.after_request
    def after_request(response):
        route = request.url_rule.rule if request.url_rule else 'unmatched'
        if route not in ('/metrics', '/static/<path:filename>'):
            REQUESTS.labels(request.method, route, response.status_code).inc()
            LATENCY.labels(route).observe(time.monotonic() - g.started)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.path.startswith('/api/') or request.path == '/tickets':
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/')
    def home():
        return render_template('index.html', events=db.session.scalars(select(Event).order_by(Event.starts_at)).all())

    @app.get('/events/<int:event_id>')
    def detail(event_id):
        event = db.get_or_404(Event, event_id)
        return render_template('detail.html', event=event, request_key=secrets.token_urlsafe(24))

    @app.get('/tickets')
    def tickets():
        return render_template('tickets.html')

    def booking_json(booking):
        return dict(code=booking.code, name=booking.name, quantity=booking.quantity, total=booking.total, event=booking.event.title, venue=booking.event.venue, city=booking.event.city, date=booking.event.starts_at.strftime('%d/%m/%Y'), time=booking.event.starts_at.strftime('%H:%M'), status='Đã xác nhận • thanh toán mô phỏng')

    @app.post('/api/bookings')
    def book():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='Dữ liệu đặt vé không hợp lệ.'), 400
        name, email, key = data.get('name'), data.get('email'), data.get('request_key')
        quantity, event_id = data.get('quantity'), data.get('event_id')
        if not isinstance(name, str) or not 2 <= len(name.strip()) <= 100:
            return jsonify(error='Họ tên cần từ 2 đến 100 ký tự.'), 400
        if not isinstance(email, str) or len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            return jsonify(error='Vui lòng nhập email hợp lệ.'), 400
        if type(quantity) is not int or not 1 <= quantity <= 10 or type(event_id) is not int:
            return jsonify(error='Mỗi lần được đặt từ 1 đến 10 vé.'), 400
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,64}', key):
            return jsonify(error='Mã yêu cầu không hợp lệ. Hãy tải lại trang.'), 400
        email = email.strip().lower()
        existing = db.session.scalar(select(Booking).where(Booking.request_key == key))
        if existing:
            if (existing.email, existing.event_id, existing.quantity, existing.name) != (email, event_id, quantity, name.strip()):
                return jsonify(error='Yêu cầu đã được sử dụng. Hãy tải lại trang.'), 409
            return jsonify(booking_json(existing)), 200
        event = db.session.get(Event, event_id)
        if not event:
            return jsonify(error='Sự kiện không tồn tại.'), 404
        now = datetime.now(timezone.utc)
        starts = event.starts_at.replace(tzinfo=timezone(timedelta(hours=7))) if event.starts_at.tzinfo is None else event.starts_at
        if starts <= now:
            return jsonify(error='Sự kiện đã kết thúc mở bán.'), 409
        price = event.price
        try:
            result = db.session.execute(update(Event).where(Event.id == event_id, Event.remaining >= quantity).values(remaining=Event.remaining - quantity))
            if result.rowcount != 1:
                db.session.rollback()
                BOOKINGS.labels('sold_out').inc()
                return jsonify(error='Không còn đủ vé. Vui lòng chọn số lượng ít hơn.'), 409
            booking = Booking(code='EF-' + secrets.token_hex(8).upper(), request_key=key, event_id=event_id, name=name.strip(), email=email, quantity=quantity, total=price * quantity)
            db.session.add(booking)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify(error='Yêu cầu vừa được xử lý. Vui lòng tra cứu vé hoặc thử lại.'), 409
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.exception('Booking transaction failed')
            return jsonify(error='Hệ thống đang bận. Vui lòng thử lại sau.'), 503
        BOOKINGS.labels('confirmed').inc()
        return jsonify(booking_json(booking)), 201

    @app.post('/api/tickets/lookup')
    def lookup():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get('code'), str) or not isinstance(data.get('email'), str):
            return jsonify(error='Vui lòng nhập mã đặt vé và email.'), 400
        booking = db.session.scalar(select(Booking).where(Booking.code == data['code'].strip().upper(), Booking.email == data['email'].strip().lower()))
        if not booking:
            return jsonify(error='Không tìm thấy vé khớp mã và email đã nhập.'), 404
        return jsonify(booking_json(booking))

    @app.get('/health/live')
    def live():
        return jsonify(status='ok', version=os.environ.get('APP_VERSION', '1.0.0'))

    @app.get('/health/ready')
    def ready():
        try:
            db.session.execute(text('SELECT 1 FROM event LIMIT 1'))
            return jsonify(status='ready')
        except SQLAlchemyError:
            db.session.rollback()
            return jsonify(status='not_ready'), 503

    @app.get('/metrics')
    def metrics():
        return app.response_class(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith('/api/'):
            return jsonify(error='Không tìm thấy tài nguyên.'), 404
        return render_template('error.html', message='Trang bạn tìm đang ở một sân khấu khác.', code=404), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        if request.path.startswith('/api/'):
            return jsonify(error='Có lỗi hệ thống. Vui lòng thử lại sau.'), 500
        return render_template('error.html', message='Hệ thống đang gặp sự cố. Vui lòng thử lại sau.', code=500), 500

    @app.cli.command('init-db')
    def init_db():
        """Create schema and seed demo events; does not reset existing data."""
        db.create_all()
        seed_events()
        click.echo('Database ready. Demo events seeded if empty.')

    return app
