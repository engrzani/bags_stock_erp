import os
import urllib.parse
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from models import db, Lot, StockEntry, WeightAdjustment, User, Client, StockDispatch, StockRequirement, ClientPayment
from datetime import datetime, date
from sqlalchemy import func
from sqlalchemy.pool import NullPool

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'bags-erp-secret-2026')

# Use DATABASE_URL env var in production (PostgreSQL), fallback to SQLite locally
_sqlite_path = '/tmp/bags_stock.db' if os.path.isdir('/tmp') else 'bags_stock.db'
database_url = os.environ.get('DATABASE_URL', f'sqlite:///{_sqlite_path}')
# Fix older postgres:// URLs
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

if database_url.startswith('postgresql'):
    # Remove params not supported by psycopg2 (channel_binding etc.)
    parsed = urllib.parse.urlparse(database_url)
    params = urllib.parse.parse_qs(parsed.query)
    params.pop('channel_binding', None)
    # Keep sslmode=require in URL only — do NOT duplicate in connect_args
    if 'sslmode' not in params:
        params['sslmode'] = ['require']
    new_query = urllib.parse.urlencode({k: v[0] for k, v in params.items()})
    database_url = urllib.parse.urlunparse(parsed._replace(query=new_query))

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Serverless-safe pool config for PostgreSQL (Neon/Vercel)
if database_url.startswith('postgresql'):
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': NullPool,
        # sslmode is already in the URL — do not add connect_args to avoid conflict
    }

db.init_app(app)

BAG_WEIGHTS = [20.0, 24.5, 25.0, 40.0, 49.0, 50.0]

with app.app_context():
    db.create_all()
    # Create default admin if no users exist
    if User.query.count() == 0:
        admin = User(
            username=os.environ.get('ADMIN_USERNAME', 'admin'),
            full_name='Administrator',
            role='admin',
            is_active=True
        )
        admin.set_password(os.environ.get('ADMIN_PASSWORD', 'admin123'))
        db.session.add(admin)
        db.session.commit()


# ─────────────────────────── AUTH ───────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def manager_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        if session.get('role') not in ('admin', 'manager'):
            flash('Access denied. Manager or Admin role required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash('Access denied. Admin role required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username, is_active=True).first()
        if user and user.check_password(password):
            session['logged_in'] = True
            session['username'] = user.username
            session['full_name'] = user.full_name or user.username
            session['role'] = user.role
            session['user_id'] = user.id
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))


# ─────────────────────────── DASHBOARD ───────────────────────────
@app.route('/')
@login_required
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

    # New stats
    total_dispatched = db.session.query(func.sum(StockDispatch.bags_dispatched)).scalar() or 0
    total_clients = Client.query.count()
    pending_requirements = StockRequirement.query.filter_by(status='pending').count()

    return render_template('dashboard.html',
                           total_bags=total_bags,
                           total_weight=round(total_weight, 2),
                           total_lots=total_lots,
                           total_adjustments=total_adjustments,
                           weight_breakdown=weight_breakdown,
                           recent_entries=recent_entries,
                           recent_lots=recent_lots,
                           bag_weights=BAG_WEIGHTS,
                           total_dispatched=total_dispatched,
                           total_clients=total_clients,
                           pending_requirements=pending_requirements)


# ─────────────────────────── LOTS ───────────────────────────
@app.route('/lots')
@login_required
def lots():
    all_lots = Lot.query.order_by(Lot.created_at.desc()).all()
    return render_template('lots.html', lots=all_lots)


@app.route('/lots/add', methods=['GET', 'POST'])
@login_required
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
@login_required
def lot_detail(lot_id):
    lot = Lot.query.get_or_404(lot_id)
    return render_template('lot_detail.html', lot=lot, bag_weights=BAG_WEIGHTS)


@app.route('/lots/<int:lot_id>/edit', methods=['GET', 'POST'])
@manager_required
def edit_lot(lot_id):
    lot = Lot.query.get_or_404(lot_id)
    if request.method == 'POST':
        lot_number = request.form['lot_number'].strip()
        # Check duplicate only if changed
        existing = Lot.query.filter_by(lot_number=lot_number).first()
        if existing and existing.id != lot.id:
            flash(f'Lot number "{lot_number}" already exists!', 'danger')
            return redirect(url_for('edit_lot', lot_id=lot_id))
        lot.lot_number = lot_number
        lot.supplier = request.form.get('supplier', '').strip()
        lot.date_received = datetime.strptime(request.form['date_received'], '%Y-%m-%d').date()
        lot.notes = request.form.get('notes', '').strip()
        db.session.commit()
        flash(f'Lot #{lot.lot_number} updated successfully!', 'success')
        return redirect(url_for('lot_detail', lot_id=lot_id))
    return render_template('edit_lot.html', lot=lot)


@app.route('/lots/<int:lot_id>/delete', methods=['POST'])
@login_required
def delete_lot(lot_id):
    lot = Lot.query.get_or_404(lot_id)
    db.session.delete(lot)
    db.session.commit()
    flash(f'Lot #{lot.lot_number} deleted.', 'warning')
    return redirect(url_for('lots'))


# ─────────────────────────── STOCK ENTRIES ───────────────────────────
@app.route('/stock')
@login_required
def stock_list():
    entries = StockEntry.query.order_by(StockEntry.created_at.desc()).all()
    return render_template('stock_list.html', entries=entries)


@app.route('/stock/add', methods=['GET', 'POST'])
@login_required
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
@login_required
def delete_stock(entry_id):
    entry = StockEntry.query.get_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    flash('Stock entry deleted.', 'warning')
    return redirect(url_for('stock_list'))


# ─────────────────────────── WEIGHT ADJUSTMENTS ───────────────────────────
@app.route('/adjustments')
@login_required
def adjustments():
    all_adj = WeightAdjustment.query.order_by(WeightAdjustment.created_at.desc()).all()
    return render_template('adjustments.html', adjustments=all_adj)


@app.route('/adjustments/add', methods=['GET', 'POST'])
@login_required
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
@login_required
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
@login_required
def api_entry(entry_id):
    e = StockEntry.query.get_or_404(entry_id)
    return jsonify({
        'id': e.id,
        'bag_type': e.bag_type,
        'current_weight': e.current_weight,
        'quantity': e.quantity,
        'available_bags': e.available_bags,
        'lot_number': e.lot.lot_number
    })


# ─────────────────────────── USER MANAGEMENT (Admin only) ───────────────────────────
@app.route('/users')
@admin_required
def users():
    all_users = User.query.order_by(User.created_at.asc()).all()
    return render_template('users.html', users=all_users)


@app.route('/users/add', methods=['GET', 'POST'])
@admin_required
def add_user():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        full_name = request.form.get('full_name', '').strip()
        role = request.form.get('role', 'viewer')

        if User.query.filter_by(username=username).first():
            flash(f'Username "{username}" already exists!', 'danger')
            return redirect(url_for('add_user'))

        user = User(username=username, full_name=full_name, role=role, is_active=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash(f'User "{username}" created successfully!', 'success')
        return redirect(url_for('users'))
    return render_template('add_user.html')


@app.route('/users/<int:user_id>/toggle', methods=['POST'])
@admin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == session.get('user_id'):
        flash('You cannot deactivate your own account!', 'danger')
        return redirect(url_for('users'))
    user.is_active = not user.is_active
    db.session.commit()
    status = 'activated' if user.is_active else 'deactivated'
    flash(f'User "{user.username}" {status}.', 'success')
    return redirect(url_for('users'))


@app.route('/users/<int:user_id>/reset-password', methods=['POST'])
@admin_required
def reset_password(user_id):
    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password', '').strip()
    if not new_password or len(new_password) < 4:
        flash('Password must be at least 4 characters.', 'danger')
        return redirect(url_for('users'))
    user.set_password(new_password)
    db.session.commit()
    flash(f'Password for "{user.username}" has been reset.', 'success')
    return redirect(url_for('users'))


# ─────────────────────────── CLIENTS ───────────────────────────
@app.route('/clients')
@login_required
def clients():
    all_clients = Client.query.order_by(Client.name).all()
    return render_template('clients.html', clients=all_clients)


@app.route('/clients/add', methods=['GET', 'POST'])
@manager_required
def add_client():
    if request.method == 'POST':
        name = request.form['name'].strip()
        contact_person = request.form.get('contact_person', '').strip()
        phone = request.form.get('phone', '').strip()
        city = request.form.get('city', '').strip()
        address = request.form.get('address', '').strip()
        notes = request.form.get('notes', '').strip()
        client = Client(name=name, contact_person=contact_person,
                        phone=phone, city=city, address=address, notes=notes,
                        opening_balance_bags=int(request.form.get('opening_balance_bags', 0) or 0),
                        opening_balance_amount=float(request.form.get('opening_balance_amount', 0) or 0))
        db.session.add(client)
        db.session.commit()
        flash(f'Client "{name}" added successfully!', 'success')
        return redirect(url_for('clients'))
    return render_template('add_client.html')


@app.route('/clients/<int:client_id>')
@login_required
def client_detail(client_id):
    client = Client.query.get_or_404(client_id)
    dispatches = StockDispatch.query.filter_by(client_id=client_id).order_by(StockDispatch.date_dispatched.asc()).all()
    payments = ClientPayment.query.filter_by(client_id=client_id).order_by(ClientPayment.date_paid.asc()).all()

    # Build combined ledger sorted by date
    ledger = []
    running_balance = client.opening_balance_amount or 0.0

    # Opening balance entry
    if client.opening_balance_bags or client.opening_balance_amount:
        ledger.append({
            'type': 'opening',
            'date': None,
            'description': f"Opening Balance — {client.opening_balance_bags} بورے",
            'bags': client.opening_balance_bags,
            'amount': client.opening_balance_amount,
            'payment': 0,
            'balance': running_balance,
        })

    # Merge dispatches and payments by date
    events = []
    for d in dispatches:
        events.append(('dispatch', d.date_dispatched, d))
    for p in payments:
        events.append(('payment', p.date_paid, p))
    events.sort(key=lambda x: x[1])

    for ev_type, ev_date, ev_obj in events:
        if ev_type == 'dispatch':
            running_balance += ev_obj.total_amount
            ledger.append({
                'type': 'dispatch',
                'date': ev_date,
                'description': f"{ev_obj.bags_dispatched} بورے × {ev_obj.weight_per_bag}kg" + (f" — {ev_obj.transporter}" if ev_obj.transporter else ""),
                'bags': ev_obj.bags_dispatched,
                'amount': ev_obj.total_amount,
                'payment': 0,
                'balance': round(running_balance, 2),
                'obj': ev_obj,
            })
        else:
            running_balance -= ev_obj.amount
            ledger.append({
                'type': 'payment',
                'date': ev_date,
                'description': ev_obj.notes or "ادائیگی",
                'bags': 0,
                'amount': 0,
                'payment': ev_obj.amount,
                'balance': round(running_balance, 2),
                'obj': ev_obj,
            })

    return render_template('client_detail.html', client=client, dispatches=dispatches,
                           payments=payments, ledger=ledger, today=date.today().isoformat())


@app.route('/clients/<int:client_id>/delete', methods=['POST'])
@admin_required
def delete_client(client_id):
    client = Client.query.get_or_404(client_id)
    db.session.delete(client)
    db.session.commit()
    flash(f'Client "{client.name}" deleted.', 'warning')
    return redirect(url_for('clients'))


@app.route('/clients/<int:client_id>/edit', methods=['GET', 'POST'])
@manager_required
def edit_client(client_id):
    client = Client.query.get_or_404(client_id)
    if request.method == 'POST':
        client.name = request.form['name'].strip()
        client.contact_person = request.form.get('contact_person', '').strip()
        client.phone = request.form.get('phone', '').strip()
        client.city = request.form.get('city', '').strip()
        client.address = request.form.get('address', '').strip()
        client.notes = request.form.get('notes', '').strip()
        client.opening_balance_bags = int(request.form.get('opening_balance_bags', 0) or 0)
        client.opening_balance_amount = float(request.form.get('opening_balance_amount', 0) or 0)
        db.session.commit()
        flash(f'Client "{client.name}" updated.', 'success')
        return redirect(url_for('client_detail', client_id=client_id))
    return render_template('edit_client.html', client=client)


@app.route('/clients/<int:client_id>/add-payment', methods=['POST'])
@manager_required
def add_payment(client_id):
    client = Client.query.get_or_404(client_id)
    amount = float(request.form.get('amount', 0) or 0)
    date_str = request.form.get('date_paid', '')
    notes = request.form.get('notes', '').strip()
    if amount <= 0:
        flash('Amount must be greater than 0.', 'danger')
        return redirect(url_for('client_detail', client_id=client_id))
    payment = ClientPayment(
        client_id=client_id,
        amount=amount,
        date_paid=datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today(),
        notes=notes
    )
    db.session.add(payment)
    db.session.commit()
    flash(f'Payment of Rs {amount:,.0f} recorded for {client.name}.', 'success')
    return redirect(url_for('client_detail', client_id=client_id))


@app.route('/clients/payment/<int:payment_id>/delete', methods=['POST'])
@admin_required
def delete_payment(payment_id):
    payment = ClientPayment.query.get_or_404(payment_id)
    client_id = payment.client_id
    db.session.delete(payment)
    db.session.commit()
    flash('Payment record deleted.', 'warning')
    return redirect(url_for('client_detail', client_id=client_id))


# ─────────────────────────── DISPATCHES ───────────────────────────
@app.route('/dispatches')
@login_required
def dispatches():
    all_dispatches = StockDispatch.query.order_by(StockDispatch.date_dispatched.desc()).all()
    total_bags = sum(d.bags_dispatched for d in all_dispatches)
    total_weight = round(sum(d.total_weight for d in all_dispatches), 2)
    total_amount = round(sum(d.total_amount for d in all_dispatches), 2)
    return render_template('dispatches.html', dispatches=all_dispatches,
                           total_bags=total_bags, total_weight=total_weight, total_amount=total_amount)


@app.route('/dispatches/add', methods=['GET', 'POST'])
@manager_required
def add_dispatch():
    all_clients = Client.query.order_by(Client.name).all()
    entries = StockEntry.query.order_by(StockEntry.created_at.desc()).all()
    if request.method == 'POST':
        client_id = int(request.form['client_id'])
        entry_id_val = request.form.get('entry_id', '').strip()
        bags_dispatched = int(request.form['bags_dispatched'])
        weight_per_bag = float(request.form['weight_per_bag'])
        rate_per_bag = float(request.form.get('rate_per_bag', 0) or 0)
        transporter = request.form.get('transporter', '').strip()
        date_str = request.form['date_dispatched']
        notes = request.form.get('notes', '').strip()

        entry_id = int(entry_id_val) if entry_id_val else None

        if entry_id:
            entry = StockEntry.query.get_or_404(entry_id)
            if bags_dispatched > entry.available_bags:
                flash(f'Cannot dispatch {bags_dispatched} bags — only {entry.available_bags} available!', 'danger')
                return redirect(url_for('add_dispatch'))
            # Deduct from stock
            entry.quantity -= bags_dispatched

        dispatch = StockDispatch(
            client_id=client_id,
            entry_id=entry_id,
            bags_dispatched=bags_dispatched,
            weight_per_bag=weight_per_bag,
            rate_per_bag=rate_per_bag,
            transporter=transporter,
            date_dispatched=datetime.strptime(date_str, '%Y-%m-%d').date(),
            notes=notes
        )
        db.session.add(dispatch)
        db.session.commit()
        flash(f'Dispatch recorded: {bags_dispatched} bags → {Client.query.get(client_id).name}', 'success')
        return redirect(url_for('dispatches'))
    return render_template('add_dispatch.html', clients=all_clients, entries=entries,
                           bag_weights=BAG_WEIGHTS, today=date.today().isoformat())


@app.route('/dispatches/<int:dispatch_id>/delete', methods=['POST'])
@admin_required
def delete_dispatch(dispatch_id):
    d = StockDispatch.query.get_or_404(dispatch_id)
    # Restore stock if linked to entry
    if d.entry_id:
        entry = StockEntry.query.get(d.entry_id)
        if entry:
            entry.quantity += d.bags_dispatched
    db.session.delete(d)
    db.session.commit()
    flash('Dispatch record deleted and stock restored.', 'warning')
    return redirect(url_for('dispatches'))


# ─────────────────────────── STOCK REQUIREMENTS ───────────────────────────
@app.route('/requirements')
@login_required
def requirements():
    all_reqs = StockRequirement.query.order_by(StockRequirement.created_at.desc()).all()
    pending = [r for r in all_reqs if r.status == 'pending']
    in_progress = [r for r in all_reqs if r.status == 'in_progress']
    return render_template('requirements.html', requirements=all_reqs,
                           pending_count=len(pending), in_progress_count=len(in_progress),
                           today=date.today())


@app.route('/requirements/add', methods=['GET', 'POST'])
@manager_required
def add_requirement():
    if request.method == 'POST':
        title = request.form['title'].strip()
        bag_type = request.form.get('bag_type', '').strip()
        weight_str = request.form.get('weight_per_bag', '').strip()
        quantity_required = int(request.form['quantity_required'])
        due_date_str = request.form.get('due_date', '').strip()
        supplier = request.form.get('supplier', '').strip()
        notes = request.form.get('notes', '').strip()

        req = StockRequirement(
            title=title,
            bag_type=bag_type,
            weight_per_bag=float(weight_str) if weight_str else None,
            quantity_required=quantity_required,
            due_date=datetime.strptime(due_date_str, '%Y-%m-%d').date() if due_date_str else None,
            supplier=supplier,
            notes=notes,
            status='pending'
        )
        db.session.add(req)
        db.session.commit()
        flash(f'Requirement "{title}" added!', 'success')
        return redirect(url_for('requirements'))
    return render_template('add_requirement.html', bag_weights=BAG_WEIGHTS, today=date.today().isoformat())


@app.route('/requirements/<int:req_id>/status', methods=['POST'])
@manager_required
def update_requirement_status(req_id):
    req = StockRequirement.query.get_or_404(req_id)
    req.status = request.form.get('status', req.status)
    db.session.commit()
    flash(f'Requirement status updated to "{req.status_label}".', 'success')
    return redirect(url_for('requirements'))


@app.route('/requirements/<int:req_id>/delete', methods=['POST'])
@admin_required
def delete_requirement(req_id):
    req = StockRequirement.query.get_or_404(req_id)
    db.session.delete(req)
    db.session.commit()
    flash('Requirement deleted.', 'warning')
    return redirect(url_for('requirements'))


if __name__ == '__main__':
    app.run(debug=True, port=5000)
