import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from sqlalchemy import select, update
from app import Booking, Event, create_app, db, seed_events


@pytest.fixture()
def app(tmp_path):
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(tmp_path / 'test.db')})
    with app.app_context():
        db.create_all()
        seed_events()
    yield app


def client_and_token(app):
    client = app.test_client()
    response = client.get('/events/1')
    html = response.get_data(as_text=True)
    token = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)
    key = re.search(r'data-request-key="([^"]+)"', html).group(1)
    return client, token, key


def payload(key, **kwargs):
    return dict(event_id=1, name='Nguyen Van An', email='an@example.com', quantity=2, request_key=key, **kwargs)


def test_pages_and_assets(app):
    c = app.test_client()
    for path in ['/', '/events/1', '/tickets', '/static/style.css', '/static/app.js', '/static/hero.svg', '/health/live', '/health/ready', '/metrics']:
        assert c.get(path).status_code == 200
    assert c.get('/events/999').status_code == 404
    assert c.get('/').get_data(as_text=True).count('class="event-card"') == 6


def test_booking_lookup_and_idempotency(app):
    c, token, key = client_and_token(app)
    headers = {'X-CSRF-Token': token}
    data = payload(key)
    data['total'] = 1  # Client may not override server pricing.
    r = c.post('/api/bookings', json=data, headers=headers)
    assert r.status_code == 201
    assert r.json['total'] == 700000
    assert c.post('/api/bookings', json=data, headers=headers).json['code'] == r.json['code']
    with app.app_context():
        assert db.session.get(Event, 1).remaining == 298
        assert len(db.session.scalars(select(Booking)).all()) == 1
    found = c.post('/api/tickets/lookup', json={'code':r.json['code'], 'email':'an@example.com'}, headers=headers)
    assert found.status_code == 200
    assert found.json['quantity'] == 2
    assert c.post('/api/tickets/lookup', json={'code':r.json['code'], 'email':'wrong@example.com'}, headers=headers).status_code == 404


@pytest.mark.parametrize('quantity', [-1, 0, 11, 1.5, True, '2'])
def test_invalid_quantity(app, quantity):
    c, token, key = client_and_token(app)
    data = payload(key)
    data['quantity'] = quantity
    assert c.post('/api/bookings', json=data, headers={'X-CSRF-Token':token}).status_code == 400
    with app.app_context():
        assert db.session.get(Event, 1).remaining == 300


def test_sold_out_rolls_back(app):
    c, token, key = client_and_token(app)
    with app.app_context():
        db.session.execute(update(Event).where(Event.id == 1).values(remaining=1))
        db.session.commit()
    assert c.post('/api/bookings', json=payload(key), headers={'X-CSRF-Token':token}).status_code == 409
    with app.app_context():
        assert db.session.get(Event, 1).remaining == 1
        assert db.session.scalar(select(Booking.id)) is None


def test_csrf_and_malformed_body(app):
    c, token, key = client_and_token(app)
    assert c.post('/api/bookings', json=payload(key)).status_code == 403
    assert c.post('/api/bookings', json=[], headers={'X-CSRF-Token':token}).status_code == 400
    assert c.post('/api/tickets/lookup', json=[], headers={'X-CSRF-Token':token}).status_code == 400


def test_concurrent_last_tickets(app):
    with app.app_context():
        db.session.execute(update(Event).where(Event.id == 1).values(remaining=3))
        db.session.commit()
    clients = [client_and_token(app) for _ in range(10)]
    def buy(item):
        c, token, key = item
        data = payload(key); data['quantity'] = 1
        return c.post('/api/bookings', json=data, headers={'X-CSRF-Token':token}).status_code
    with ThreadPoolExecutor(max_workers=10) as pool:
        statuses = list(pool.map(buy, clients))
    assert statuses.count(201) == 3
    assert statuses.count(409) == 7
    with app.app_context():
        assert db.session.get(Event, 1).remaining == 0
        assert len(db.session.scalars(select(Booking)).all()) == 3


def test_expired_event(app):
    c, token, key = client_and_token(app)
    with app.app_context():
        db.session.get(Event, 1).starts_at = datetime(2020, 1, 1)
        db.session.commit()
    assert c.post('/api/bookings', json=payload(key), headers={'X-CSRF-Token':token}).status_code == 409


def test_readiness_checks_schema(app):
    with app.app_context():
        db.drop_all()
    assert app.test_client().get('/health/ready').status_code == 503
    assert app.test_client().get('/health/live').status_code == 200
