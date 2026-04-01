from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


# ─────────────────────────── USER ───────────────────────────
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(100), default='')
    role = db.Column(db.String(20), nullable=False, default='viewer')  # admin / manager / viewer
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def role_label(self):
        return {'admin': 'Administrator', 'manager': 'Manager', 'viewer': 'Viewer'}.get(self.role, self.role)

    @property
    def role_color(self):
        return {'admin': 'danger', 'manager': 'primary', 'viewer': 'secondary'}.get(self.role, 'secondary')


# ─────────────────────────── CLIENT ───────────────────────────
class Client(db.Model):
    __tablename__ = 'clients'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    contact_person = db.Column(db.String(100), default='')
    phone = db.Column(db.String(30), default='')
    city = db.Column(db.String(100), default='')
    address = db.Column(db.Text, default='')
    notes = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    dispatches = db.relationship('StockDispatch', backref='client', lazy=True)
    payments = db.relationship('ClientPayment', backref='client', lazy=True, cascade='all, delete-orphan')

    opening_balance_bags = db.Column(db.Integer, default=0)        # بورے (B/F bags)
    opening_balance_amount = db.Column(db.Float, default=0.0)     # لانٹا (B/F amount in Rs)

    @property
    def total_bags_received(self):
        return self.opening_balance_bags + sum(d.bags_dispatched for d in self.dispatches)

    @property
    def total_weight_received(self):
        return round(sum(d.total_weight for d in self.dispatches), 2)

    @property
    def total_amount_due(self):
        """Total amount due = opening balance + all dispatches amount"""
        return round(self.opening_balance_amount + sum(d.total_amount for d in self.dispatches), 2)

    @property
    def total_payments_received(self):
        return round(sum(p.amount for p in self.payments), 2)

    @property
    def balance_due(self):
        return round(self.total_amount_due - self.total_payments_received, 2)


# ─────────────────────────── LOT ───────────────────────────
class Lot(db.Model):
    __tablename__ = 'lots'
    id = db.Column(db.Integer, primary_key=True)
    lot_number = db.Column(db.String(50), unique=True, nullable=False)
    supplier = db.Column(db.String(100))
    date_received = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Relationship
    entries = db.relationship('StockEntry', backref='lot', lazy=True, cascade='all, delete-orphan')

    def total_bags(self):
        return sum(e.quantity for e in self.entries)

    def total_weight(self):
        return sum(e.total_weight for e in self.entries)


class StockEntry(db.Model):
    __tablename__ = 'stock_entries'
    id = db.Column(db.Integer, primary_key=True)
    lot_id = db.Column(db.Integer, db.ForeignKey('lots.id'), nullable=False)
    bag_type = db.Column(db.String(100), nullable=False)
    original_weight = db.Column(db.Float, nullable=False)   # per bag weight when received
    current_weight = db.Column(db.Float, nullable=False)    # per bag weight after adjustment
    quantity = db.Column(db.Integer, nullable=False)
    date_entry = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Relationship
    adjustments = db.relationship('WeightAdjustment', backref='entry', lazy=True, cascade='all, delete-orphan')
    dispatches = db.relationship('StockDispatch', backref='entry', lazy=True)

    @property
    def total_weight(self):
        return self.current_weight * self.quantity

    @property
    def weight_diff(self):
        return (self.original_weight - self.current_weight) * self.quantity

    @property
    def dispatched_bags(self):
        return sum(d.bags_dispatched for d in self.dispatches)

    @property
    def available_bags(self):
        return self.quantity - self.dispatched_bags


class WeightAdjustment(db.Model):
    __tablename__ = 'weight_adjustments'
    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey('stock_entries.id'), nullable=False)
    bags_adjusted = db.Column(db.Integer, nullable=False)
    old_weight = db.Column(db.Float, nullable=False)
    new_weight = db.Column(db.Float, nullable=False)
    reason = db.Column(db.String(200))
    date_adjusted = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def weight_saved(self):
        return (self.old_weight - self.new_weight) * self.bags_adjusted


# ─────────────────────────── STOCK DISPATCH ───────────────────────────
class StockDispatch(db.Model):
    __tablename__ = 'stock_dispatches'
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    entry_id = db.Column(db.Integer, db.ForeignKey('stock_entries.id'), nullable=True)
    bags_dispatched = db.Column(db.Integer, nullable=False)
    weight_per_bag = db.Column(db.Float, nullable=False)
    rate_per_bag = db.Column(db.Float, default=0.0)    # قیمت فی بوری (Rs per bag)
    transporter = db.Column(db.String(100), default='')  # گاڑی والا / ٹرانسپورٹر
    date_dispatched = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def total_weight(self):
        return round(self.bags_dispatched * self.weight_per_bag, 2)

    @property
    def total_amount(self):
        return round(self.bags_dispatched * (self.rate_per_bag or 0), 2)


# ─────────────────────────── STOCK REQUIREMENT ───────────────────────────
class StockRequirement(db.Model):
    __tablename__ = 'stock_requirements'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    bag_type = db.Column(db.String(100), default='')
    weight_per_bag = db.Column(db.Float, nullable=True)
    quantity_required = db.Column(db.Integer, nullable=False)
    due_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending / in_progress / fulfilled / cancelled
    supplier = db.Column(db.String(100), default='')
    notes = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def status_color(self):
        return {'pending': 'warning', 'in_progress': 'primary', 'fulfilled': 'success', 'cancelled': 'secondary'}.get(self.status, 'secondary')

    @property
    def status_label(self):
        return {'pending': 'Pending', 'in_progress': 'In Progress', 'fulfilled': 'Fulfilled', 'cancelled': 'Cancelled'}.get(self.status, self.status)


# ─────────────────────────── CLIENT PAYMENT ───────────────────────────
class ClientPayment(db.Model):
    __tablename__ = 'client_payments'
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)           # ادا کردہ رقم (Rs)
    date_paid = db.Column(db.Date, nullable=False)
    notes = db.Column(db.String(200), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

