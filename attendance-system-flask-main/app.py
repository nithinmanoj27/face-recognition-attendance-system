import cv2
import face_recognition
import numpy as np
import psycopg2
import psycopg2.extras
import base64
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session, send_from_directory, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc, ForeignKeyConstraint, and_
from sqlalchemy.dialects.postgresql import JSONB
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
import yagmail
import random
from datetime import datetime, timedelta, timezone, date
import uuid
from collections import defaultdict
import io
import openpyxl
import traceback
from dotenv import load_dotenv

# --- Load Environment Variables ---
load_dotenv() 

# --- App Initialization ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-fallback-secret-key-for-dev')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)

# --- Folder for annotations ---
ANNOTATION_DIR = os.path.join(app.root_path, 'static', 'annotated_uploads')
if not os.path.exists(ANNOTATION_DIR): os.makedirs(ANNOTATION_DIR)

# --- Email Configuration ---
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'your-email@gmail.com')
SENDER_PASSWORD = os.environ.get('SENDER_PASSWORD', 'your-16-character-app-password')

# --- Database Configuration ---
DB_NAME = os.environ.get('DB_NAME', 'attendance_db')
DB_USER = os.environ.get('DB_USER', 'projectuser')
DB_PASS = os.environ.get('DB_PASS', 'projectpass')
DB_HOST = os.environ.get('DB_HOST', 'localhost') # 'localhost' for local, 'db' for Docker
DB_PORT = os.environ.get('DB_PORT', '5432')

app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'index'
login_manager.login_message_category = 'info'

# === DATABASE MODELS ===
# (All models: enrollments, SubjectStaff, Teacher, Student, Subject, AttendanceRecord, AnnotatedPhoto... are identical to V27)
# ... [models identical to V27] ...
# Association Table: Students <-> Subjects
enrollments = db.Table('enrollments',
    db.Column('student_roll_number', db.String(80), db.ForeignKey('students.roll_number', ondelete='CASCADE'), primary_key=True),
    db.Column('subject_id', db.Integer, db.ForeignKey('subjects.id', ondelete='CASCADE'), primary_key=True)
)

# Association Table: Teachers <-> Subjects (for TAs/Profs)
class SubjectStaff(db.Model):
    __tablename__ = 'subject_staff'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id', ondelete='CASCADE'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id', ondelete='CASCADE'), nullable=False)
    role_in_subject = db.Column(db.String(50), nullable=False, default='TA') # 'Professor' or 'TA'
    is_approved_by_prof = db.Column(db.Boolean, default=False, nullable=False)
    __table_args__ = (db.UniqueConstraint('teacher_id', 'subject_id', name='_teacher_subject_uc'),)
    teacher = db.relationship('Teacher', backref='staff_assignments')
    subject = db.relationship('Subject', backref='staff_assignments')


class Teacher(UserMixin, db.Model):
    __tablename__ = 'teachers'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='TA') # 'Admin', 'Professor', 'TA'
    is_approved = db.Column(db.Boolean, default=False, nullable=False) # Admin approval
    # subjects_staffed defined by backref from SubjectStaff
    annotated_photos = db.relationship('AnnotatedPhoto', backref='uploader', lazy=True, cascade="all, delete-orphan")
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

class Student(UserMixin, db.Model):
    __tablename__ = 'students'
    roll_number = db.Column(db.String(80), primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)
    face_encodings = db.Column(JSONB, nullable=True)
    is_verified = db.Column(db.Boolean, default=False, nullable=False) # Email + Face
    otp = db.Column(db.String(6), nullable=True)
    otp_generated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    subjects = db.relationship('Subject', secondary=enrollments, lazy='dynamic',
                               backref=db.backref('students', lazy='dynamic'))
    attendance_records = db.relationship('AttendanceRecord', backref='student', lazy=True, cascade="all, delete-orphan")
    def get_id(self): return self.roll_number
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        if not self.password_hash: return False
        return check_password_hash(self.password_hash, password)

class Subject(db.Model):
    __tablename__ = 'subjects'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False) # e.g., CS101
    name = db.Column(db.String(150), nullable=False) # e.g., Intro to Programming
    # staff defined by backref from SubjectStaff
    attendance_records = db.relationship('AttendanceRecord', backref='subject', lazy=True, cascade="all, delete-orphan")
    annotated_photos = db.relationship('AnnotatedPhoto', backref='subject', lazy=True, cascade="all, delete-orphan")

class AttendanceRecord(db.Model):
    __tablename__ = 'attendance_records'
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id', ondelete='CASCADE'), nullable=False)
    student_roll_number = db.Column(db.String(80), db.ForeignKey('students.roll_number', ondelete='CASCADE'), nullable=False)
    attendance_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(10), nullable=False)
    __table_args__ = (db.UniqueConstraint('subject_id', 'attendance_date', 'student_roll_number', name='_subject_date_roll_uc'),)

class AnnotatedPhoto(db.Model):
    __tablename__ = 'annotated_photos'
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id', ondelete='CASCADE'), nullable=False)
    attendance_date = db.Column(db.Date, nullable=False)
    image_path = db.Column(db.String(255), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id', ondelete='SET NULL'), nullable=True)
    __table_args__ = (db.UniqueConstraint('subject_id', 'attendance_date', 'image_path', name='_subject_date_image_uc'),)

# === Utility Functions ===
def setup_database():
    with app.app_context():
        try:
            db.create_all() # This creates all tables based on the models above
            print("Database setup complete. All new tables are ready.")
        except Exception as e:
            db.session.rollback()
            print(f"Error during database setup: {e}")

def get_db_connection():
    """Establbcishes a direct connection to the database for raw SQL if needed."""
    # This function now reads from environment variables
    DB_NAME_LOCAL = os.environ.get('DB_NAME', 'attendance_db')
    DB_USER_LOCAL = os.environ.get('DB_USER', 'projectuser')
    DB_PASS_LOCAL = os.environ.get('DB_PASS', 'projectpass')
    DB_HOST_LOCAL = os.environ.get('DB_HOST', 'localhost')
    DB_PORT_LOCAL = os.environ.get('DB_PORT', '5432')
    
    try: 
        return psycopg2.connect(
            dbname=DB_NAME_LOCAL, 
            user=DB_USER_LOCAL, 
            password=DB_PASS_LOCAL, 
            host=DB_HOST_LOCAL, 
            port=DB_PORT_LOCAL
        )
    except psycopg2.OperationalError as e: 
        print(f"DB Connect Error: {e}"); 
        return None

def send_email(recipient_email, subject, body):
    if SENDER_EMAIL == "your-email@gmail.com" or SENDER_PASSWORD == "your-16-character-app-password":
        print(f"--- EMAIL SKIPPED (Config missing) ---\nTo: {recipient_email}\nSub: {subject}\nBody: {body}\n---"); return False
    try: yagmail.SMTP(SENDER_EMAIL, SENDER_PASSWORD).send(to=recipient_email, subject=subject, contents=body); print(f"Email sent to {recipient_email}"); return True
    except Exception as e: print(f"Email Error to {recipient_email}: {e}"); return False

def process_and_annotate_faces(image_bytes, known_faces_encodings, known_faces_data):
    try:
        nparr = np.frombuffer(image_bytes, np.uint8); img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None: return set(), None
        rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        locs = face_recognition.face_locations(rgb_img); encs = face_recognition.face_encodings(rgb_img, locs)
        found_rolls = set()
        for (top, right, bottom, left), enc in zip(locs, encs):
            matches = face_recognition.compare_faces(known_faces_encodings, enc, tolerance=0.5)
            name = "Unknown"; roll = None
            if True in matches:
                dists = face_recognition.face_distance(known_faces_encodings, enc); best_idx = np.argmin(dists)
                if matches[best_idx]: roll, name = known_faces_data[best_idx]; found_rolls.add(roll)
            cv2.rectangle(img, (left, top), (right, bottom), (0, 255, 0), 2); cv2.rectangle(img, (left, bottom - 35), (right, bottom), (0, 255, 0), cv2.FILLED)
            font = cv2.FONT_HERSHEY_DUPLEX; display = f"{name} ({roll})" if roll else "Unknown"
            cv2.putText(img, display, (left + 6, bottom - 6), font, 0.7, (255, 255, 255), 1)
        return found_rolls, img
    except Exception as e: print(f"Face Process Error: {e}"); return set(), None

# === Flask-Login ===
@login_manager.user_loader
def load_user(user_id):
    if session.get('user_type') == 'teacher': return db.session.get(Teacher, int(user_id))
    elif session.get('user_type') == 'student': return db.session.get(Student, str(user_id))
    return None

@login_manager.unauthorized_handler
def unauthorized():
    flash('Login required to access this page.', 'warning')
    if request.endpoint and ('teacher_portal' in request.endpoint or 'approve_teacher' in request.endpoint):
        return redirect(url_for('teacher_portal'))
    if request.endpoint and 'student_portal' in request.endpoint:
        return redirect(url_for('student_portal'))
    return redirect(url_for('index'))

# === Routes ===
# ... [All routes from V27 are here, unchanged] ...
# === Routes ===
@app.route("/")
def index():
    return render_template('index.html') 

# === Teacher Routes ===
@app.route("/teacher")
def teacher_portal():
    pending_teachers = []; approved_teachers = []; all_students = []
    subjects_managed = []; available_tas = []; pending_ta_requests = []
    attendance_subjects = [] # Subjects they can take attendance for
    
    if current_user.is_authenticated and isinstance(current_user, Teacher) and current_user.is_approved:
        if current_user.role == 'Admin':
            pending_teachers = Teacher.query.filter_by(is_approved=False).order_by(Teacher.id).all()
            approved_teachers = Teacher.query.filter(Teacher.is_approved==True, Teacher.id != current_user.id).order_by(Teacher.username).all()
            all_students = Student.query.order_by(Student.roll_number).all()
            attendance_subjects = Subject.query.order_by(Subject.name).all()
        
        elif current_user.role == 'Professor':
            subjects_managed_query = Subject.query.join(SubjectStaff).filter(
                SubjectStaff.teacher_id == current_user.id,
                SubjectStaff.role_in_subject == 'Professor'
            )
            subjects_managed = subjects_managed_query.order_by(Subject.name).all()
            attendance_subjects = subjects_managed # Profs can take attendance for subjects they manage
            available_tas = Teacher.query.filter_by(role='TA', is_approved=True).all()
            subject_ids = [s.id for s in subjects_managed]
            if subject_ids:
                pending_ta_requests = SubjectStaff.query.filter(
                    SubjectStaff.subject_id.in_(subject_ids),
                    SubjectStaff.is_approved_by_prof == False,
                    SubjectStaff.role_in_subject == 'TA'
                ).all()

        elif current_user.role == 'TA':
            # TAs can only take attendance for subjects they are *approved* for
            attendance_subjects = Subject.query.join(SubjectStaff).filter(
                SubjectStaff.teacher_id == current_user.id,
                SubjectStaff.is_approved_by_prof == True
            ).order_by(Subject.name).all()
            
    return render_template('teacher.html', 
                           pending_teachers=pending_teachers,
                           approved_teachers=approved_teachers,
                           all_students=all_students,
                           subjects_managed=subjects_managed,
                           available_tas=available_tas,
                           pending_ta_requests=pending_ta_requests,
                           attendance_subjects=attendance_subjects)


@app.route("/teacher-register", methods=['POST'])
def teacher_register():
    try:
        username = request.form.get('reg_username'); email = request.form.get('reg_email'); password = request.form.get('reg_password'); role = request.form.get('reg_role')
        if not all([username, email, password, role]): flash('All fields required.', 'danger'); return redirect(url_for('teacher_portal'))
        if role not in ['Professor', 'TA']: flash('Invalid role.', 'danger'); return redirect(url_for('teacher_portal'))
        if len(password) < 6: flash('Password too short.', 'danger'); return redirect(url_for('teacher_portal'))
        if '@' not in email or '.' not in email: flash('Invalid email.', 'danger'); return redirect(url_for('teacher_portal'))
        if Teacher.query.filter_by(username=username).first(): flash('Username exists.', 'danger'); return redirect(url_for('teacher_portal'))
        if Teacher.query.filter_by(email=email).first(): flash('Email exists.', 'danger'); return redirect(url_for('teacher_portal'))
        new_teacher = Teacher(username=username, email=email, role=role, is_approved=False); new_teacher.set_password(password); db.session.add(new_teacher); db.session.commit()
        admins = Teacher.query.filter_by(role='Admin', is_approved=True).all()
        admin_emails = [admin.email for admin in admins if admin.email]
        if admin_emails: send_email(admin_emails, "New Staff Request", f"User: {username}\nRole: {role}\nEmail: {email}\nApprove in portal.")
        flash('Request submitted. Awaiting Admin approval.', 'success'); return redirect(url_for('teacher_portal'))
    except Exception as e: db.session.rollback(); print(f"Teacher Reg Error: {e}"); flash(f'Error: {e}', 'danger'); return redirect(url_for('teacher_portal'))

@app.route("/login", methods=['POST'])
def teacher_login():
    username = request.form.get('username'); password = request.form.get('password')
    teacher = Teacher.query.filter_by(username=username).first()
    if teacher and teacher.check_password(password):
        if not teacher.is_approved: flash('Account awaiting Admin approval.', 'warning'); return redirect(url_for('teacher_portal'))
        login_user(teacher); session['user_type'] = 'teacher'; flash(f'Login successful! Welcome {teacher.role} {teacher.username}.', 'success'); return redirect(url_for('teacher_portal'))
    else: flash('Invalid credentials.', 'danger'); return redirect(url_for('teacher_portal'))

@app.route("/approve-teacher/<int:teacher_id>", methods=['POST'])
@login_required
def approve_teacher(teacher_id):
    if not (isinstance(current_user, Teacher) and current_user.role == 'Admin'): flash('Unauthorized.', 'danger'); return redirect(url_for('teacher_portal'))
    teacher = db.session.get(Teacher, teacher_id)
    if not teacher: flash('Not found.', 'danger')
    elif teacher.is_approved: flash(f'{teacher.username} already approved.', 'info')
    else:
        try: teacher.is_approved = True; db.session.commit(); flash(f'{teacher.username} approved!', 'success'); send_email(teacher.email, "Account Approved", f"Hi {teacher.username},\nAccount approved.")
        except Exception as e: db.session.rollback(); print(f"Approve Error {teacher_id}: {e}"); flash(f'Error: {e}', 'danger')
    return redirect(url_for('teacher_portal'))

@app.route("/deny-teacher/<int:teacher_id>", methods=['POST'])
@login_required
def deny_teacher(teacher_id):
    if not (isinstance(current_user, Teacher) and current_user.role == 'Admin'): flash('Unauthorized.', 'danger'); return redirect(url_for('teacher_portal'))
    teacher = db.session.get(Teacher, teacher_id)
    if not teacher: flash('Not found.', 'danger')
    elif teacher.is_approved: flash(f'Cannot deny approved teacher ({teacher.username}).', 'warning')
    else:
        try: name = teacher.username; email = teacher.email; db.session.delete(teacher); db.session.commit(); flash(f'Registration for {name} denied.', 'success'); send_email(email, "Registration Denied", f"Hi {name},\nRegistration denied.")
        except Exception as e: db.session.rollback(); print(f"Deny Error {teacher_id}: {e}"); flash(f'Error: {e}', 'danger')
    return redirect(url_for('teacher_portal'))

@app.route("/remove-teacher/<int:teacher_id>", methods=['POST'])
@login_required
def remove_teacher(teacher_id):
    if not (isinstance(current_user, Teacher) and current_user.role == 'Admin'): flash('Unauthorized.', 'danger'); return redirect(url_for('teacher_portal'))
    if current_user.id == teacher_id: flash('Cannot remove self.', 'danger'); return redirect(url_for('teacher_portal'))
    teacher = db.session.get(Teacher, teacher_id)
    if not teacher: flash('Not found.', 'danger')
    else:
        try: name = teacher.username; email = teacher.email; db.session.delete(teacher); db.session.commit(); flash(f'{name} removed.', 'success'); send_email(email, "Account Removed", f"Hi {name},\nAccount removed.")
        except Exception as e: db.session.rollback(); print(f"Remove Error {teacher_id}: {e}"); flash(f'Error: {e}', 'danger')
    return redirect(url_for('teacher_portal'))

@app.route("/remove-student/<string:roll_number>", methods=['POST'])
@login_required
def remove_student(roll_number):
    if not (isinstance(current_user, Teacher) and current_user.role == 'Admin'): flash('Unauthorized.', 'danger'); return redirect(url_for('teacher_portal'))
    student = db.session.get(Student, roll_number)
    if not student: flash(f'Student {roll_number} not found.', 'danger')
    else:
        try: name = student.name; email = student.email; db.session.delete(student); db.session.commit(); flash(f'Student {name} ({roll_number}) removed.', 'success'); send_email(email, "Account Removed", f"Hi {name},\nStudent account removed.")
        except Exception as e: db.session.rollback(); print(f"Remove Student Error {roll_number}: {e}"); flash(f'Error: {e}', 'danger')
    return redirect(url_for('teacher_portal'))


@app.route("/logout")
@login_required
def logout():
    user_type = session.get('user_type', 'guest'); logout_user(); session.clear(); flash('Logged out.', 'success')
    if user_type == 'teacher': return redirect(url_for('teacher_portal'))
    if user_type == 'student': return redirect(url_for('student_portal'))
    return redirect(url_for('index'))

@app.route("/create-subject", methods=['POST'])
@login_required
def create_subject():
    if not (isinstance(current_user, Teacher) and current_user.role == 'Professor'): flash('Unauthorized.', 'danger'); return redirect(url_for('teacher_portal'))
    code = request.form.get('subject_code'); name = request.form.get('subject_name')
    if not all([code, name]): flash('Code and Name required.', 'danger'); return redirect(url_for('teacher_portal'))
    if Subject.query.filter_by(code=code).first(): flash(f'Subject code {code} exists.', 'danger'); return redirect(url_for('teacher_portal'))
    try:
        new_subject = Subject(code=code, name=name); db.session.add(new_subject); db.session.commit()
        staff_link = SubjectStaff(teacher_id=current_user.id, subject_id=new_subject.id, role_in_subject='Professor', is_approved_by_prof=True)
        db.session.add(staff_link); db.session.commit(); flash(f'Subject "{name}" created!', 'success')
    except Exception as e: db.session.rollback(); print(f"Create Subject Error: {e}"); flash(f'Error: {e}', 'danger')
    return redirect(url_for('teacher_portal'))

@app.route("/add-ta-to-subject", methods=['POST'])
@login_required
def add_ta_to_subject():
    if not (isinstance(current_user, Teacher) and current_user.role == 'Professor'): flash('Unauthorized.', 'danger'); return redirect(url_for('teacher_portal'))
    ta_id = request.form.get('ta_id'); subject_id = request.form.get('subject_id')
    if not all([ta_id, subject_id]): flash('TA and Subject required.', 'danger'); return redirect(url_for('teacher_portal'))
    prof_is_staff = SubjectStaff.query.filter_by(teacher_id=current_user.id, subject_id=subject_id, role_in_subject='Professor').first()
    if not prof_is_staff: flash('Unauthorized: You do not manage this subject.', 'danger'); return redirect(url_for('teacher_portal'))
    existing_link = SubjectStaff.query.filter_by(teacher_id=ta_id, subject_id=subject_id).first()
    if existing_link: flash('TA already assigned.', 'warning'); return redirect(url_for('teacher_portal'))
    ta = db.session.get(Teacher, ta_id)
    if not (ta and ta.is_approved and ta.role == 'TA'): flash('Invalid or unapproved TA.', 'danger'); return redirect(url_for('teacher_portal'))
    try:
        new_link = SubjectStaff(teacher_id=ta_id, subject_id=subject_id, role_in_subject='TA', is_approved_by_prof=False)
        db.session.add(new_link); db.session.commit(); flash(f'TA {ta.username} requested for subject. Please approve.', 'success')
    except Exception as e: db.session.rollback(); print(f"Add TA Error: {e}"); flash(f'Error: {e}', 'danger')
    return redirect(url_for('teacher_portal'))

@app.route("/approve-ta/<int:staff_id>", methods=['POST'])
@login_required
def approve_ta(staff_id):
    if not (isinstance(current_user, Teacher) and current_user.role == 'Professor'): flash('Unauthorized.', 'danger'); return redirect(url_for('teacher_portal'))
    staff_link = db.session.get(SubjectStaff, staff_id)
    if not staff_link: flash('Record not found.', 'danger'); return redirect(url_for('teacher_portal'))
    prof_is_staff = SubjectStaff.query.filter_by(teacher_id=current_user.id, subject_id=staff_link.subject_id, role_in_subject='Professor').first()
    if not prof_is_staff: flash('Unauthorized: You do not manage this subject.', 'danger'); return redirect(url_for('teacher_portal'))
    try:
        staff_link.is_approved_by_prof = True; db.session.commit(); flash(f'TA {staff_link.teacher.username} approved for {staff_link.subject.name}!', 'success')
        send_email(staff_link.teacher.email, "TA Assignment Approved", f"Hi {staff_link.teacher.username},\nYour TA assignment for {staff_link.subject.name} was approved.")
    except Exception as e: db.session.rollback(); print(f"Approve TA Error: {e}"); flash(f'Error: {e}', 'danger')
    return redirect(url_for('teacher_portal'))

@app.route("/remove-ta-from-subject/<int:staff_id>", methods=['POST'])
@login_required
def remove_ta_from_subject(staff_id):
    if not (isinstance(current_user, Teacher) and current_user.role == 'Professor'): flash('Unauthorized.', 'danger'); return redirect(url_for('teacher_portal'))
    staff_link = db.session.get(SubjectStaff, staff_id)
    if not staff_link: flash('Record not found.', 'danger'); return redirect(url_for('teacher_portal'))
    prof_is_staff = SubjectStaff.query.filter_by(teacher_id=current_user.id, subject_id=staff_link.subject_id, role_in_subject='Professor').first()
    if not prof_is_staff: flash('Unauthorized: You do not manage this subject.', 'danger'); return redirect(url_for('teacher_portal'))
    try:
        ta_name = staff_link.teacher.username; subject_name = staff_link.subject.name; was_pending = not staff_link.is_approved_by_prof
        db.session.delete(staff_link); db.session.commit()
        if was_pending: flash(f'TA request for {ta_name} on {subject_name} denied.', 'success')
        else: flash(f'TA {ta_name} removed from {subject_name}.', 'success')
        send_email(staff_link.teacher.email, "Removed from Subject", f"Hi {ta_name},\nYour TA assignment for {subject_name} was removed.")
    except Exception as e: db.session.rollback(); print(f"Remove TA Error: {e}"); flash(f'Error: {e}', 'danger')
    return redirect(url_for('teacher_portal'))

@app.route("/unenroll-student-from-subject", methods=['POST'])
@login_required
def unenroll_student_from_subject():
    if not (isinstance(current_user, Teacher) and current_user.role == 'Professor'):
        flash('Unauthorized: Only Professors can manage subject enrollments.', 'danger')
        return redirect(url_for('teacher_portal'))
    subject_id = request.form.get('subject_id'); roll_number = request.form.get('roll_number')
    if not subject_id or not roll_number:
        flash('Missing subject or student information.', 'danger'); return redirect(url_for('teacher_portal'))
    prof_is_staff = SubjectStaff.query.filter_by(teacher_id=current_user.id, subject_id=subject_id, role_in_subject='Professor').first()
    if not prof_is_staff:
        flash('Unauthorized: You do not manage this subject.', 'danger'); return redirect(url_for('teacher_portal'))
    student = db.session.get(Student, roll_number); subject = db.session.get(Subject, subject_id)
    if not student or not subject:
        flash('Student or Subject not found.', 'danger'); return redirect(url_for('teacher_portal'))
    try:
        student.subjects.remove(subject); db.session.commit()
        flash(f"Student {student.name} ({student.roll_number}) has been unenrolled from {subject.name}.", 'success')
    except Exception as e:
        db.session.rollback(); print(f"Error unenrolling student: {e}"); flash(f"An error occurred: {e}", 'danger')
    return redirect(url_for('teacher_portal'))


# === STUDENT ROUTES (RE-IMPLEMENTED) ===
# ... [All student routes from V22 are here, unchanged] ...
@app.route("/student-portal")
def student_portal():
    enrolled_subjects = []
    available_subjects = []
    if current_user.is_authenticated and isinstance(current_user, Student):
        enrolled_subjects = current_user.subjects.order_by(Subject.name).all()
        enrolled_subject_ids = [s.id for s in enrolled_subjects]
        available_subjects = Subject.query.filter(db.not_(Subject.id.in_(enrolled_subject_ids))).order_by(Subject.name).all()
    return render_template('student-portal.html',
                           enrolled_subjects=enrolled_subjects,
                           available_subjects=available_subjects)

@app.route("/student-register", methods=['POST'])
def student_register():
    try:
        roll = request.form.get('roll_number'); name = request.form.get('name'); email = request.form.get('email'); pwd = request.form.get('password')
        if not all([roll, name, email, pwd]): return jsonify({'error': 'All fields required.'}), 400
        if len(pwd) < 6: return jsonify({'error': 'Password too short.'}), 400
        if '@' not in email or '.' not in email: return jsonify({'error': 'Invalid email.'}), 400
        if db.session.get(Student, roll): return jsonify({'error': 'Roll Number exists.'}), 409
        if Student.query.filter_by(email=email).first(): return jsonify({'error': 'Email exists.'}), 409
        otp = str(random.randint(100000, 999999)); otp_time = datetime.now(timezone.utc)
        student = Student(roll_number=roll, name=name, email=email, otp=otp, otp_generated_at=otp_time)
        student.set_password(pwd); db.session.add(student); db.session.commit()
        subject = "Verify Email"; body = f"Hi {name},\nCode: {otp}\nExpires in 10 mins."
        if send_email(student.email, subject, body): 
            return jsonify({'message': f'Registered! Code sent to {student.email}.'})
        else: 
             db.session.rollback(); print(f"Email fail, rolling back {roll}"); return jsonify({'error': 'Failed to send verification email.'}), 500
    except Exception as e:
        db.session.rollback(); print(f"Student register error: {e}")
        unique_msg = 'Roll Number or Email already exists.' if "violates unique constraint" in str(e).lower() else f'DB error: {e}'
        return jsonify({'error': unique_msg}), 500

@app.route("/student-login", methods=['POST'])
def student_login():
    try:
        roll = request.form.get('roll_number'); pwd = request.form.get('password')
        if not all([roll, pwd]): return jsonify({'error': 'Roll/Password required.'}), 400
        student = db.session.get(Student, roll)
        if not student: return jsonify({'error': 'Roll Number not found.'}), 404
        if not student.password_hash: return jsonify({'error': 'Password not set. Use Forgot Password.'}), 401
        if not student.check_password(pwd): return jsonify({'error': 'Invalid password.'}), 401
        login_user(student); session['user_type'] = 'student'; session.pop('update_verified', None)
        return jsonify({'message': 'Login successful!', 'reload': True})
    except Exception as e: print(f"Student login error: {e}"); return jsonify({'error': f'Internal error: {e}'}), 500

@app.route("/verify-otp", methods=['POST'])
def verify_otp():
    try:
        roll = request.form.get('roll_number'); otp_attempt = request.form.get('otp')
        if not all([roll, otp_attempt]): return jsonify({'error': 'Roll/OTP required.'}), 400
        student = db.session.get(Student, roll)
        if not student: return jsonify({'error': 'Student not found.'}), 404
        if student.otp is None: return jsonify({'error': 'No pending/expired OTP.'}), 400
        if student.otp != otp_attempt: return jsonify({'error': 'Invalid OTP.'}), 400
        if student.otp_generated_at is None or (datetime.now(timezone.utc) - student.otp_generated_at) > timedelta(minutes=10):
            student.otp = None; student.otp_generated_at = None; db.session.commit(); return jsonify({'error': 'OTP expired.'}), 400
        login_user(student); session['user_type'] = 'student'; session['update_verified'] = True
        student.otp = None; student.otp_generated_at = None; 
        db.session.commit()
        return jsonify({'message': 'Verified! Proceed with face enrollment.', 'is_verified': student.is_verified})
    except Exception as e: db.session.rollback(); print(f"OTP verify error: {e}"); return jsonify({'error': f'Internal error: {e}'}), 500

@app.route("/request-password-reset-otp", methods=['POST'])
def request_password_reset_otp():
    try:
        roll = request.form.get('roll_number')
        if not roll: return jsonify({'error': 'Roll Number required.'}), 400
        student = db.session.get(Student, roll)
        if not student: print(f"Pwd reset for non-existent roll: {roll}"); return jsonify({'message': 'If account exists, code sent.'})
        otp = str(random.randint(100000, 999999)); otp_time = datetime.now(timezone.utc)
        student.otp = otp; student.otp_generated_at = otp_time; db.session.commit()
        subject = "Password Reset Code"; body = f"Hi {student.name},\nCode: {otp}\nExpires in 10 mins."
        if send_email(student.email, subject, body): return jsonify({'message': f'Reset code sent to {student.email}.'})
        else: db.session.rollback(); return jsonify({'error': 'Failed to send code.'}), 500
    except Exception as e: db.session.rollback(); print(f"Request pwd reset error: {e}"); return jsonify({'error': 'Internal error.'}), 500

@app.route("/reset-password-with-otp", methods=['POST'])
def reset_password_with_otp():
    try:
        roll = request.form.get('roll_number'); otp_attempt = request.form.get('otp'); new_pwd = request.form.get('new_password')
        if not all([roll, otp_attempt, new_pwd]): return jsonify({'error': 'All fields required.'}), 400
        if len(new_pwd) < 6: return jsonify({'error': 'Password too short.'}), 400
        student = db.session.get(Student, roll)
        if not student: return jsonify({'error': 'Invalid Roll/OTP.'}), 400
        if student.otp is None: return jsonify({'error': 'Invalid/expired OTP.'}), 400
        if student.otp != otp_attempt: return jsonify({'error': 'Invalid OTP.'}), 400
        if student.otp_generated_at is None or (datetime.now(timezone.utc) - student.otp_generated_at) > timedelta(minutes=10):
            student.otp = None; student.otp_generated_at = None; db.session.commit(); return jsonify({'error': 'OTP expired.'}), 400
        student.set_password(new_pwd); student.otp = None; student.otp_generated_at = None; db.session.commit()
        return jsonify({'message': 'Password reset! Log in with new password.'})
    except Exception as e: db.session.rollback(); print(f"Reset pwd error: {e}"); return jsonify({'error': 'Internal error.'}), 500

@app.route("/request-update-otp", methods=['POST'])
@login_required
def request_update_otp():
    if not isinstance(current_user, Student): return jsonify({'error': 'Unauthorized'}), 401
    try:
        student = db.session.get(Student, current_user.roll_number)
        if not student: logout_user(); return jsonify({'error': 'Student not found.'}), 404
        otp = str(random.randint(100000, 999999)); otp_time = datetime.now(timezone.utc)
        student.otp = otp; student.otp_generated_at = otp_time; db.session.commit()
        subject = "Profile Update Code"; body = f"Hi {student.name},\nCode: {otp}\nExpires in 10 mins."
        if send_email(student.email, subject, body): return jsonify({'message': f'Code sent to {student.email}.'})
        else: db.session.rollback(); return jsonify({'error': 'Failed to send OTP.'}), 500
    except Exception as e: db.session.rollback(); print(f"Req update OTP error: {e}"); return jsonify({'error': 'Failed to send OTP.'}), 500

@app.route("/verify-update-otp", methods=['POST'])
@login_required
def verify_update_otp():
    if not isinstance(current_user, Student): return jsonify({'error': 'Unauthorized'}), 401
    try:
        otp_attempt = request.form.get('otp')
        if not otp_attempt: return jsonify({'error': 'OTP required.'}), 400
        student = db.session.get(Student, current_user.roll_number)
        if not student: logout_user(); return jsonify({'error': 'Student not found.'}), 404
        if student.otp is None: return jsonify({'error': 'Invalid/expired OTP.'}), 400
        if student.otp != otp_attempt: return jsonify({'error': 'Invalid OTP.'}), 400
        if student.otp_generated_at is None or (datetime.now(timezone.utc) - student.otp_generated_at) > timedelta(minutes=10):
            student.otp = None; student.otp_generated_at = None; db.session.commit(); return jsonify({'error': 'OTP expired.'}), 400
        student.otp = None; student.otp_generated_at = None; session['update_verified'] = True; db.session.commit()
        return jsonify({'message': 'Verified! Proceed with update.'})
    except Exception as e: db.session.rollback(); print(f"Verify update OTP error: {e}"); return jsonify({'error': 'Internal error.'}), 500

@app.route("/get-student-details")
@login_required
def get_student_details():
    if not isinstance(current_user, Student): return jsonify({'error': 'Unauthorized'}), 401
    student = db.session.get(Student, current_user.roll_number)
    if not student: logout_user(); return jsonify({'error': 'Student not found.'}), 404
    return jsonify({'name': student.name, 'roll_number': student.roll_number, 'email': student.email, 'is_verified': student.is_verified})

@app.route("/enroll", methods=['POST'])
@login_required
def enroll_student_face():
    if not (isinstance(current_user, Student) and session.get('update_verified') == True):
        return jsonify({'error': 'Unauthorized. Verify with OTP first.'}), 401
    roll = current_user.get_id(); student = db.session.get(Student, roll)
    if not student: logout_user(); return jsonify({'error': 'Student not found.'}), 404
    if 'video' not in request.files: return jsonify({'error': 'No video file.'}), 400
    video_file = request.files['video']
    if video_file.filename == '': return jsonify({'error': 'No video selected.'}), 400
    video_bytes = video_file.read(); temp_dir = '/tmp';
    if not os.path.exists(temp_dir): os.makedirs(temp_dir)
    temp_video_path = f"{temp_dir}/{uuid.uuid4()}_temp.webm"
    try:
        with open(temp_video_path, 'wb') as f: f.write(video_bytes)
        vid_cap = cv2.VideoCapture(temp_video_path)
        if not vid_cap.isOpened(): raise Exception(f"Cannot open video: {temp_video_path}")
        encodings = []; frame_count = 0; processed_count = 0
        while vid_cap.isOpened() and processed_count < 100:
            ret, frame = vid_cap.read();
            if not ret: break
            if frame_count % 5 == 0:
                processed_count += 1
                try:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    locs = face_recognition.face_locations(rgb, model="hog")
                    if locs:
                        f_encs = face_recognition.face_encodings(rgb, locs)
                        if len(f_encs) == 1: encodings.append(f_encs[0].tolist())
                except Exception as frame_err: print(f"Frame {frame_count} err: {frame_err}")
            frame_count += 1
            if len(encodings) >= 20: break
        vid_cap.release()
        MIN_ENCODINGS = 5
        if len(encodings) < MIN_ENCODINGS:
            print(f"Enroll failed {roll}: Found {len(encodings)}/{MIN_ENCODINGS}"); return jsonify({'error': f'Need {MIN_ENCODINGS} clear faces. Try better lighting.'}), 400
        print(f"Extracted {len(encodings)} for {roll}.")
        student.face_encodings = encodings; student.is_verified = True; session.pop('update_verified', None); db.session.commit()
        return jsonify({'message': f'Face enrolled! {len(encodings)} samples saved.', 'reload': True})
    except Exception as e:
        db.session.rollback(); print(f"Video process error {roll}: {e}"); traceback.print_exc(); return jsonify({'error': f'Face process error: {e}. Try again.'}), 500
    finally:
        if os.path.exists(temp_video_path): os.remove(temp_video_path)

@app.route("/enroll-in-subject", methods=['POST'])
@login_required
def enroll_in_subject():
    if not isinstance(current_user, Student): flash('Unauthorized.', 'danger'); return redirect(url_for('student_portal'))
    subject_id = request.form.get('subject_id')
    if not subject_id: flash('Subject ID required.', 'danger'); return redirect(url_for('student_portal'))
    subject = db.session.get(Subject, subject_id)
    if not subject: flash('Subject not found.', 'danger'); return redirect(url_for('student_portal'))
    try:
        current_user.subjects.append(subject); db.session.commit()
        flash(f"Successfully enrolled in {subject.name}!", 'success')
    except Exception as e:
        db.session.rollback(); print(f"Enroll subject error: {e}"); flash(f"Already enrolled or error.", 'warning')
    return redirect(url_for('student_portal'))

@app.route("/unenroll-from-subject", methods=['POST'])
@login_required
def unenroll_from_subject():
    if not isinstance(current_user, Student): flash('Unauthorized.', 'danger'); return redirect(url_for('student_portal'))
    subject_id = request.form.get('subject_id')
    if not subject_id: flash('Subject ID required.', 'danger'); return redirect(url_for('student_portal'))
    subject = db.session.get(Subject, subject_id)
    if not subject: flash('Subject not found.', 'danger'); return redirect(url_for('student_portal'))
    try:
        current_user.subjects.remove(subject); db.session.commit()
        flash(f"Successfully unenrolled from {subject.name}.", 'success')
    except Exception as e:
        db.session.rollback(); print(f"Unenroll error: {e}"); flash(f"Error: {e}", 'danger')
    return redirect(url_for('student_portal'))


# --- ATTENDANCE & REPORT ROUTES (RE-IMPLEMENTED) ---
# (These are all the functions from V24, re-added)

@app.route("/process-attendance", methods=['POST'])
@login_required
def process_attendance():
    if not isinstance(current_user, Teacher): return jsonify({'error': 'Unauthorized.'}), 401
    try:
        subject_id = request.form.get('subject_id'); att_date_str = request.form.get('attendance_date'); images = request.files.getlist('photos')
        if not all([subject_id, att_date_str]): return jsonify({'error': 'Subject and Date required.'}), 400
        if not images or all(img.filename == '' for img in images): return jsonify({'error': 'No photos.'}), 400
        try: att_date = datetime.strptime(att_date_str, '%Y-%m-%d').date()
        except ValueError: return jsonify({'error': 'Invalid date format.'}), 400
        
        staff_link = SubjectStaff.query.filter(SubjectStaff.teacher_id == current_user.id, SubjectStaff.subject_id == subject_id, SubjectStaff.is_approved_by_prof == True).first()
        if not staff_link and current_user.role != 'Admin': return jsonify({'error': 'Unauthorized: Not approved for this subject.'}), 403

        subject = db.session.get(Subject, subject_id)
        if not subject: return jsonify({'error': 'Subject not found.'}), 404
        
        enrolled_students = subject.students.filter(Student.is_verified == True, Student.face_encodings.isnot(None)).all()
        all_rolls_in_subject = {s.roll_number for s in enrolled_students}
        known_encs = []; known_data = []
        for s in enrolled_students:
            if s.face_encodings:
                for enc_list in s.face_encodings:
                    try: known_encs.append(np.array(enc_list)); known_data.append((s.roll_number, s.name))
                    except Exception as e: print(f"Encoding error {s.roll_number}: {e}")
        if not known_encs: return jsonify({'error': 'No verified students enrolled in this subject.'}), 400

        present_rolls = set(); annotated_paths = []; photo_recs = []; processed_at_least_one_photo = False
        for img_file in images:
            if img_file.filename == '': continue
            img_bytes = img_file.read(); found_ids, anno_img = process_and_annotate_faces(img_bytes, known_encs, known_data)
            if anno_img is not None:
                processed_at_least_one_photo = True; fname = f"{uuid.uuid4()}.jpg"; fpath = os.path.join(ANNOTATION_DIR, fname)
                try:
                    cv2.imwrite(fpath, anno_img); web_path = url_for('static', filename=f'annotated_uploads/{fname}'); annotated_paths.append(web_path)
                    photo_recs.append(AnnotatedPhoto(subject_id=subject_id, attendance_date=att_date, image_path=web_path, teacher_id=current_user.id))
                except Exception as write_err: print(f"Save error {fname}: {write_err}")
            present_rolls.update(found_ids)
        if not processed_at_least_one_photo: return jsonify({'error': 'Could not process submitted photos.'}), 400

        present = list(present_rolls); absent = list(all_rolls_in_subject - present_rolls)
        conn = None
        try:
            AnnotatedPhoto.query.filter_by(subject_id=subject_id, attendance_date=att_date).delete()
            conn = get_db_connection();
            if not conn: raise Exception("DB connection fail.")
            cur = conn.cursor(); sql = "INSERT INTO attendance_records (subject_id, attendance_date, student_roll_number, status) VALUES (%s, %s, %s, %s) ON CONFLICT (subject_id, attendance_date, student_roll_number) DO UPDATE SET status = EXCLUDED.status;"
            pres_data = [(subject_id, att_date, r, 'present') for r in present]; abs_data = [(subject_id, att_date, r, 'absent') for r in absent]
            if pres_data: psycopg2.extras.execute_batch(cur, sql, pres_data)
            if abs_data: psycopg2.extras.execute_batch(cur, sql, abs_data)
            conn.commit()
            if photo_recs: db.session.add_all(photo_recs); db.session.commit()
            print(f"Att {att_date} (Subj {subject_id}): P:{present}, A:{absent}")
        except Exception as db_err:
             if conn: conn.rollback(); db.session.rollback(); print(f"Save error: {db_err}"); traceback.print_exc(); return jsonify({'error': f'DB save error: {db_err}'}), 500
        finally:
            if conn: conn.close()
        email_ok = True
        try:
            email_map = {s.roll_number: s.email for s in enrolled_students}; subject_name = subject.name
            for r in present: email_ok = send_email(email_map.get(r), f"Present: {subject_name} ({att_date})", f"Hi {r},\nPresent for {subject_name} on {att_date}.") and email_ok
            for r in absent: email_ok = send_email(email_map.get(r), f"Absent: {subject_name} ({att_date})", f"Hi {r},\nAbsent for {subject_name} on {att_date}.") and email_ok
        except Exception as e: print(f"Email error: {e}"); email_ok = False
        return jsonify({'message': f'Attendance for {subject.name} saved!{"" if email_ok else " (Email send issues.)"}', 'annotated_images': annotated_paths})
    except Exception as e: db.session.rollback(); print(f"Unhandled /process error: {e}"); traceback.print_exc(); return jsonify({'error': f'Internal error: {e}'}), 500
    
@app.route("/report")
@login_required
def report():
    """Displays the live attendance report, now subject-aware."""
    subject_id = request.args.get('subject_id', type=int)
    if not subject_id:
        flash('No subject selected.', 'danger')
        if isinstance(current_user, Teacher): return redirect(url_for('teacher_portal'))
        else: return redirect(url_for('student_portal'))
        
    subject = db.session.get(Subject, subject_id)
    if not subject:
        flash('Subject not found.', 'danger'); return redirect(url_for('index'))
        
    # Security Check: Is this user allowed to see this report?
    is_teacher_view = False
    if isinstance(current_user, Teacher) and current_user.is_approved:
        if current_user.role == 'Admin': is_teacher_view = True
        else:
            staff_link = SubjectStaff.query.filter_by(teacher_id=current_user.id, subject_id=subject_id, is_approved_by_prof=True).first()
            if staff_link: is_teacher_view = True # They are approved staff
                
    elif isinstance(current_user, Student):
        if subject not in current_user.subjects.all():
            flash('Unauthorized: You are not enrolled in this subject.', 'danger')
            return redirect(url_for('student_portal'))
        is_teacher_view = False # Show read-only view
    else:
        flash('Unauthorized.', 'danger'); return redirect(url_for('index'))

    try:
        students = subject.students.filter_by(is_verified=True).order_by(Student.roll_number).all()
        records = AttendanceRecord.query.filter_by(subject_id=subject_id).order_by(AttendanceRecord.attendance_date).all()
        
        unique_dates_obj = sorted(list({rec.attendance_date for rec in records}))
        unique_dates_str = [d.strftime('%Y-%m-%d') for d in unique_dates_obj]
        students_data = []
        for student in students:
            student_dict = {'roll_number': student.roll_number, 'name': student.name, 'email': student.email, 'attendance': {date_str: '-' for date_str in unique_dates_str}, 'present_count': 0, 'absent_count': 0, 'total_marked': 0, 'percentage': 0.0}
            students_data.append(student_dict)
        student_map = {s_data['roll_number']: s_data for s_data in students_data}
        for record in records:
            if record.student_roll_number in student_map:
                student_entry = student_map[record.student_roll_number]
                date_str = record.attendance_date.strftime('%Y-%m-%d')
                student_entry['attendance'][date_str] = record.status
                if record.status == 'present': student_entry['present_count'] += 1
                elif record.status == 'absent': student_entry['absent_count'] += 1
        for student_entry in students_data:
            student_entry['total_marked'] = student_entry['present_count'] + student_entry['absent_count']
            if student_entry['total_marked'] > 0: student_entry['percentage'] = round((student_entry['present_count'] / student_entry['total_marked']) * 100, 1)
            
        return render_template('report.html', 
                               students_data=students_data, 
                               unique_dates=unique_dates_str, 
                               is_teacher_view=is_teacher_view,
                               subject=subject) # Pass subject info to template
    except Exception as e: print(f"Report Error: {e}"); traceback.print_exc(); flash(f"Report Error: {e}", 'danger');
    if isinstance(current_user, Teacher): return redirect(url_for('teacher_portal'))
    else: return redirect(url_for('student_portal'))
    
@app.route("/update-attendance-status", methods=['POST'])
@login_required
def update_attendance_status():
    """Handles teacher edits from the report page."""
    if not (isinstance(current_user, Teacher) and current_user.is_approved): return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = request.json; roll = data.get('roll_number'); date_str = data.get('date'); status = data.get('status'); subject_id = data.get('subject_id')
        if not all([roll, date_str, status, subject_id]): return jsonify({'error': 'Missing data.'}), 400
        
        staff_link = SubjectStaff.query.filter_by(teacher_id=current_user.id, subject_id=subject_id, is_approved_by_prof=True).first()
        if not staff_link and current_user.role != 'Admin': return jsonify({'error': 'Unauthorized for this subject.'}), 403
        
        if status not in ['present', 'absent', '-']: return jsonify({'error': 'Invalid status.'}), 400
        try: att_date = date.fromisoformat(date_str)
        except ValueError: return jsonify({'error': 'Invalid date format.'}), 400
        
        record = AttendanceRecord.query.filter_by(student_roll_number=roll, attendance_date=att_date, subject_id=subject_id).first()
        if status == '-':
            if record: db.session.delete(record)
        else:
            if record: record.status = status
            else:
                student = db.session.get(Student, roll);
                if not student: return jsonify({'error': f'Student {roll} not found.'}), 404
                record = AttendanceRecord(subject_id=subject_id, student_roll_number=roll, attendance_date=att_date, status=status); db.session.add(record)
        db.session.commit(); print(f"Att updated by {current_user.username}: {roll} (Subj {subject_id}) on {date_str} to {status}")
        return jsonify({'message': 'Attendance updated!'})
    except Exception as e: db.session.rollback(); print(f"Update Att Error: {e}"); return jsonify({'error': f'DB error: {e}'}), 500
    
@app.route("/download-report")
@login_required
def download_report():
    """Generates and serves the attendance report as Excel."""
    if not (isinstance(current_user, Teacher) and current_user.is_approved): flash('Unauthorized.', 'danger'); return redirect(url_for('teacher_portal'))
    subject_id = request.args.get('subject_id', type=int)
    if not subject_id: flash('Subject ID required.', 'danger'); return redirect(url_for('teacher_portal'))
    
    subject = db.session.get(Subject, subject_id)
    if not subject: flash('Subject not found.', 'danger'); return redirect(url_for('teacher_portal'))
    
    staff_link = SubjectStaff.query.filter_by(teacher_id=current_user.id, subject_id=subject_id, is_approved_by_prof=True).first()
    if not staff_link and current_user.role != 'Admin': flash('Unauthorized for this subject.', 'danger'); return redirect(url_for('teacher_portal'))
    
    try:
        students = subject.students.filter_by(is_verified=True).order_by(Student.roll_number).all()
        records = AttendanceRecord.query.filter_by(subject_id=subject_id).order_by(AttendanceRecord.attendance_date).all()
        unique_dates_obj = sorted(list({rec.attendance_date for rec in records}))
        unique_dates_str = [d.strftime('%Y-%m-%d') for d in unique_dates_obj]
        
        attendance_map = defaultdict(lambda: {date_str: '-' for date_str in unique_dates_str})
        present_counts = defaultdict(int); absent_counts = defaultdict(int)
        for r in records:
            date_str = r.attendance_date.strftime('%Y-%m-%d'); attendance_map[r.student_roll_number][date_str] = r.status
            if r.status == 'present': present_counts[r.student_roll_number] += 1
            elif r.status == 'absent': absent_counts[r.student_roll_number] += 1
            
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = f"{subject.code} Report"
        
        # Format based on uploaded file
        headers = ["Student_Rollno"] + [f"Class_{i+1}" for i in range(len(unique_dates_str))]
        ws.append(headers)
        sub_headers = [""] + unique_dates_str # Second row for dates
        ws.append(sub_headers)
        
        for s in students:
            roll = s.roll_number
            status_list = []
            for date_str in unique_dates_str:
                status = attendance_map[roll].get(date_str, '-')
                if status == 'present': status_list.append('Y')
                elif status == 'absent': status_list.append('N')
                else: status_list.append('')
            row = [roll] + status_list
            ws.append(row)
        
        excel_stream = io.BytesIO(); wb.save(excel_stream); excel_stream.seek(0)
        ts = datetime.now().strftime("%Y%m%d"); fname = f"attendance_{subject.code}_{ts}.xlsx"
        return Response(excel_stream, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': f'attachment;filename={fname}'})
    except Exception as e: print(f"Excel Error: {e}"); traceback.print_exc(); flash(f"Excel Error: {e}", 'danger'); return redirect(url_for('teacher_portal'))
    
@app.route("/get-student-attendance-data", methods=['GET'])
@login_required
def get_student_attendance_data():
    """Fetches attendance history, stats, and photos for ONE subject."""
    if not isinstance(current_user, Student): return jsonify({'error': 'Unauthorized'}), 401
    
    subject_id = request.args.get('subject_id', type=int)
    if not subject_id: return jsonify({'error': 'Subject ID required.'}), 400
        
    roll = current_user.roll_number
    subject = db.session.get(Subject, subject_id)
    if not subject: return jsonify({'error': 'Subject not found.'}), 404
    if subject not in current_user.subjects.all(): return jsonify({'error': 'You are not enrolled in this subject.'}), 403

    records = AttendanceRecord.query.filter_by(student_roll_number=roll, subject_id=subject_id).order_by(desc(AttendanceRecord.attendance_date)).all()
    attendance_data = []; present_count = 0; absent_count = 0
    for rec in records:
        attendance_data.append({'date': rec.attendance_date.strftime('%Y-%m-%d'), 'status': rec.status})
        if rec.status == 'present': present_count += 1
        elif rec.status == 'absent': absent_count += 1
        
    total_marked = present_count + absent_count
    percentage = round((present_count / total_marked * 100), 1) if total_marked > 0 else 0.0
    
    latest_photo_rec = AnnotatedPhoto.query.filter_by(subject_id=subject_id).order_by(desc(AnnotatedPhoto.attendance_date), desc(AnnotatedPhoto.id)).first()
    photo_data = []; latest_date_str = None; status_today = 'N/A'
    
    if latest_photo_rec:
        latest_date = latest_photo_rec.attendance_date; latest_date_str = latest_date.strftime('%Y-%m-%d')
        status_rec = AttendanceRecord.query.filter_by(student_roll_number=roll, attendance_date=latest_date, subject_id=subject_id).first()
        if status_rec: status_today = status_rec.status
        photos = AnnotatedPhoto.query.filter_by(subject_id=subject_id, attendance_date=latest_date).order_by(AnnotatedPhoto.id).all()
        photo_data = [p.image_path for p in photos]
        
    return jsonify({
        'attendance_history': attendance_data, 'present_count': present_count, 'absent_count': absent_count,
        'total_marked': total_marked, 'percentage': percentage, 'annotated_photos': photo_data,
        'most_recent_photo_date': latest_date_str, 'student_status_today': status_today
        })

# === Main Execution ===
if __name__ == "__main__":
    conn = get_db_connection()
    if conn is None:
        print("FATAL: DB connection failed.")
    else:
        conn.close()
        setup_database() # This will create the new tables
        app.run(host='0.0.0.0', port=8080, debug=True)