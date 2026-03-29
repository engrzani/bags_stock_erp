import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from models import db, Lot, StockEntry, WeightAdjustment
from datetime import datetime, date
from sqlalchemy import func

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'bags-erp-secret-2026')

# Use DATABASE_URL env var in production (PostgreSQL), fallback to SQLite locally
database_url = os.environ.get('DATABASE_URL', 'sqlite:///bags_stock.db')
# Fix older postgres:// URLs (Heroku/Railway/Neon style)
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

BAG_WEIGHTS = [20.0, 24.5, 25.0, 40.0, 49.0, 50.0]

with app.app_context():
    db.create_all()


# ─────────────────────────── DASHBOARD ───────────────────────────
@app.route('/')
def dashboard():
    total_bags = db.session.query(func.sum(StockEntry.quantity)).scalar() or 0
    total_weight = db.session.query(
        func.sum(StockEntry.current_weight * StockEntry.quantity)
    ).scalar() or 0.0
    total_lots = Lot.query.count()
    total_adjustments = WeightAdjustment.query.count()

    # Weight breakdown per category
    weight_breakdown = db.session.query(
        StockEntry.current_weight,
        func.sum(StockEntry.quantity).label('total_qty'),
        func.sum(StockEntry.current_weight * StockEntry.quantity).label('total_wt')
    ).group_by(StockEntry.current_weight).all()

    # Recent 5 entries
    recent_entries = StockEntry.query.order_by(StockEntry.created_at.desc()).limit(5).all()
    # Recent 5 lots
    recent_lots = Lot.query.order_by(Lot.created_at.desc()).limit(5).all()

    return render_template('dashboard.html',
                           total_bags=total_bags,
                           total_weight=round(total_weight, 2),
                           total_lots=total_lots,
                           total_adjustments=total_adjustments,
                           weight_breakdown=weight_breakdown,
                           recent_entries=recent_entries,
                           recent_lots=recent_lots,
                           bag_weights=BAG_WEIGHTS)


# ─────────────────────────── LOTS ───────────────────────────
@app.route('/lots')
def lots():
    all_lots = Lot.query.order_by(Lot.created_at.desc()).all()
    return render_template('lots.html', lots=all_lots)


@app.route('/lots/add', methods=['GET', 'POST'])
def add_lot():
    if request.method == 'POST':
        lot_number = request.form['lot_number'].strip()
        supplier = request.form.get('supplier', '').strip()
        date_str = request.form['date_received']
        notes = request.form.get('notes', '').strip()

        if Lot.query.filter_by(lot_number=lot_number).first():
            flash(f'Lot number "{lot_number}" already exists!', 'danger')
            return redirect(url_for('add_lot'))

        lot = Lot(
            lot_number=lot_number,
            supplier=supplier,
            date_received=datetime.strptime(date_str, '%Y-%m-%d').date(),
            notes=notes
        )
        db.session.add(lot)
        db.session.commit()
        flash(f'Lot #{lot_number} added successfully!', 'success')
        return redirect(url_for('lots'))

    return render_template('add_lot.html', today=date.today().isoformat())


@app.route('/lots/<int:lot_id>')
def lot_detail(lot_id):
    lot = Lot.query.get_or_404(lot_id)
    return render_template('lot_detail.html', lot=lot, bag_weights=BAG_WEIGHTS)


@app.route('/lots/<int:lot_id>/delete', methods=['POST'])
def delete_lot(lot_id):
    lot = Lot.query.get_or_404(lot_id)
    db.session.delete(lot)
    db.session.commit()
    flash(f'Lot #{lot.lot_number} deleted.', 'warning')
    return redirect(url_for('lots'))


# ─────────────────────────── STOCK ENTRIES ───────────────────────────
@app.route('/stock')
def stock_list():
    entries = StockEntry.query.order_by(StockEntry.created_at.desc()).all()
    return render_template('stock_list.html', entries=entries)


@app.route('/stock/add', methods=['GET', 'POST'])
def add_stock():
    lots = Lot.query.order_by(Lot.lot_number).all()
    if request.method == 'POST':
        lot_id = int(request.form['lot_id'])
        bag_type = request.form['bag_type'].strip()
        original_weight = float(request.form['original_weight'])
        current_weight = float(request.form['current_weight'])
        quantity = int(request.form['quantity'])
        date_str = request.form['date_entry']
        notes = request.form.get('notes', '').strip()

        entry = StockEntry(
            lot_id=lot_id,
            bag_type=bag_type,
            original_weight=original_weight,
            current_weight=current_weight,
            quantity=quantity,
            date_entry=datetime.strptime(date_str, '%Y-%m-%d').date(),
            notes=notes
        )
        db.session.add(entry)
        db.session.commit()
        flash('Stock entry added successfully!', 'success')
        return redirect(url_for('stock_list'))

    return render_template('add_stock.html', lots=lots,
                           bag_weights=BAG_WEIGHTS,
                           today=date.today().isoformat())


@app.route('/stock/<int:entry_id>/delete', methods=['POST'])
def delete_stock(entry_id):
    entry = StockEntry.query.get_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    flash('Stock entry deleted.', 'warning')
    return redirect(url_for('stock_list'))


# ─────────────────────────── WEIGHT ADJUSTMENTS ───────────────────────────
@app.route('/adjustments')
def adjustments():
    all_adj = WeightAdjustment.query.order_by(WeightAdjustment.created_at.desc()).all()
    return render_template('adjustments.html', adjustments=all_adj)


@app.route('/adjustments/add', methods=['GET', 'POST'])
def add_adjustment():
    entries = StockEntry.query.order_by(StockEntry.created_at.desc()).all()
    if request.method == 'POST':
        entry_id = int(request.form['entry_id'])
        bags_adjusted = int(request.form['bags_adjusted'])
        new_weight = float(request.form['new_weight'])
        reason = request.form.get('reason', '').strip()
        date_str = request.form['date_adjusted']

        entry = StockEntry.query.get_or_404(entry_id)
        if bags_adjusted > entry.quantity:
            flash('Bags to adjust cannot exceed total bags in that entry!', 'danger')
            return redirect(url_for('add_adjustment'))

        old_weight = entry.current_weight

        adj = WeightAdjustment(
            entry_id=entry_id,
            bags_adjusted=bags_adjusted,
            old_weight=old_weight,
            new_weight=new_weight,
            reason=reason,
            date_adjusted=datetime.strptime(date_str, '%Y-%m-%d').date()
        )
        db.session.add(adj)

        # Update entry current weight if ALL bags are adjusted
        if bags_adjusted == entry.quantity:
            entry.current_weight = new_weight
        else:
            # Split entry: create new entry for adjusted bags
            new_entry = StockEntry(
                lot_id=entry.lot_id,
                bag_type=entry.bag_type,
                original_weight=entry.original_weight,
                current_weight=new_weight,
                quantity=bags_adjusted,
                date_entry=entry.date_entry,
                notes=f'Split from Entry #{entry.id} - Weight adjusted {old_weight}kg → {new_weight}kg'
            )
            entry.quantity -= bags_adjusted
            db.session.add(new_entry)

        db.session.commit()
        flash(f'Weight adjustment recorded! {bags_adjusted} bags: {old_weight}kg → {new_weight}kg', 'success')
        return redirect(url_for('adjustments'))

    return render_template('add_adjustment.html', entries=entries,
                           bag_weights=BAG_WEIGHTS,
                           today=date.today().isoformat())


# ─────────────────────────── REPORTS ───────────────────────────
@app.route('/reports')
def reports():
    # By weight category
    by_weight = db.session.query(
        StockEntry.current_weight,
        func.sum(StockEntry.quantity).label('total_qty'),
        func.sum(StockEntry.current_weight * StockEntry.quantity).label('total_wt')
    ).group_by(StockEntry.current_weight).order_by(StockEntry.current_weight).all()

    # By lot
    lots_data = Lot.query.order_by(Lot.date_received.desc()).all()

    # Total summary
    total_bags = db.session.query(func.sum(StockEntry.quantity)).scalar() or 0
    total_weight = db.session.query(
        func.sum(StockEntry.current_weight * StockEntry.quantity)
    ).scalar() or 0.0
    total_adj = WeightAdjustment.query.count()
    weight_saved = sum(
        (a.old_weight - a.new_weight) * a.bags_adjusted
        for a in WeightAdjustment.query.all()
    )

    return render_template('reports.html',
                           by_weight=by_weight,
                           lots_data=lots_data,
                           total_bags=total_bags,
                           total_weight=round(total_weight, 2),
                           total_adj=total_adj,
                           weight_saved=round(weight_saved, 2))


# ─────────────────────────── API (for JS fetch) ───────────────────────────
@app.route('/api/entry/<int:entry_id>')
def api_entry(entry_id):
    e = StockEntry.query.get_or_404(entry_id)
    return jsonify({
        'id': e.id,
        'bag_type': e.bag_type,
        'current_weight': e.current_weight,
        'quantity': e.quantity,
        'lot_number': e.lot.lot_number
    })


if __name__ == '__main__':
    app.run(debug=True, port=5000)
