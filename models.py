from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

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

    @property
    def total_weight(self):
        return self.current_weight * self.quantity

    @property
    def weight_diff(self):
        return (self.original_weight - self.current_weight) * self.quantity


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
