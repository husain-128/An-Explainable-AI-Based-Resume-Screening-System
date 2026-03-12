from flask import Flask, request, render_template, flash, redirect, url_for
import os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from pypdf import PdfReader
import string
import json
import secrets
from datetime import datetime
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from models import db, User, ResumeAnalysis
from flask_login import LoginManager, login_user, login_required, logout_user, current_user

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)  # Change in production
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB max upload size
app.config['UPLOAD_FOLDER'] = 'uploads'

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Predefined list of common skills
SKILLS_LIST = [
    'python', 'java', 'javascript', 'machine learning', 'data analysis',
    'sql', 'html', 'css', 'react', 'flask', 'tensorflow', 'pandas',
    'numpy', 'git', 'docker', 'aws', 'linux', 'c++', 'r', 'excel',
    'mongodb', 'php', 'mysql', 'node.js', 'angular', 'vue', 'django',
    'spring', 'kubernetes', 'azure', 'gcp', 'postgresql', 'oracle',
    'c#', 'ruby', 'rails', 'scala', 'hadoop', 'spark', 'tableau',
    'power bi', 'sas', 'matlab', 'swift', 'kotlin', 'flutter', 'ionic',
    'firebase', 'heroku', 'jenkins', 'ansible', 'terraform', 'graphql',
    'rest api', 'soap', 'xml', 'json', 'linux', 'windows', 'macos',
    'bash', 'powershell', 'vim', 'emacs', 'intellij', 'vscode', 'eclipse'
]

# Ensure uploads folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def normalize_text(text):
    """Normalize text: lowercase, remove punctuation, strip extra whitespace."""
    text = text.lower()
    text = text.translate(str.maketrans('', '', string.punctuation))
    return ' '.join(text.split())

def extract_text_from_pdf(file_path):
    """Extract text from PDF using PyPDF2."""
    try:
        reader = PdfReader(file_path)
        text = ''
        for page in reader.pages:
            text += page.extract_text()
        return text
    except Exception as e:
        return None

def get_skills_in_text(text, skills_list):
    """Find skills in text using case-insensitive substring match."""
    text_lower = text.lower()
    return [skill for skill in skills_list if skill.lower() in text_lower]

def calculate_tfidf_similarity(resume_text, job_desc):
    """Calculate TF-IDF based similarity score."""
    try:
        # Create TF-IDF vectorizer
        vectorizer = TfidfVectorizer()
        # Fit and transform both texts
        tfidf_matrix = vectorizer.fit_transform([resume_text, job_desc])
        # Calculate cosine similarity
        similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])
        return round(similarity[0][0] * 100, 2)
    except:
        return 0.0

def calculate_match_percentage(matched_skills, job_skills):
    """Calculate match percentage based on skills matching."""
    if job_skills:
        return round((len(matched_skills) / len(job_skills)) * 100, 2)
    else:
        return 0.0

def generate_suggestions(missing_skills, matched_skills):
    """Generate improvement suggestions based on missing skills."""
    suggestions = []
    if missing_skills:
        suggestions.append(f"Consider adding {len(missing_skills)} missing skills to improve your match score.")
        if len(missing_skills) <= 3:
            suggestions.append("Focus on learning these key skills first.")
        else:
            suggestions.append("Prioritize the most in-demand skills from the missing list.")
    if matched_skills:
        suggestions.append(f"Your {len(matched_skills)} matched skills are a strong foundation.")
    if not missing_skills and not matched_skills:
        suggestions.append("Ensure your resume contains relevant technical skills.")
    return suggestions

@app.route('/')
@login_required
def index():
    """User dashboard after login."""
    return render_template('dashboard.html')

@app.route('/analyze', methods=['GET', 'POST'])
@login_required
def analyze():
    """Analyze resume and job description."""
    if request.method == 'POST':
        file = request.files.get('resume')
        job_desc = request.form.get('job_desc', '').strip()
        
        # Validation
        if not file or file.filename == '':
            flash('Please upload a resume PDF.', 'error')
            return redirect(url_for('analyze'))
        if not job_desc:
            flash('Please enter a job description.', 'error')
            return redirect(url_for('analyze'))
        if not file.filename.lower().endswith('.pdf'):
            flash('Only PDF files are allowed.', 'error')
            return redirect(url_for('analyze'))
        
        # Secure filename and save
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # Extract text from PDF
        resume_text = extract_text_from_pdf(file_path)
        if resume_text is None:
            flash('Unable to read the PDF. Please ensure it is a text-based PDF.', 'error')
            os.remove(file_path)
            return redirect(url_for('analyze'))
        
        # Get skills from resume and job desc
        resume_skills = get_skills_in_text(resume_text, SKILLS_LIST)
        job_skills = get_skills_in_text(job_desc, SKILLS_LIST)
        
        # Calculate matched and missing skills
        matched_skills = list(set(resume_skills) & set(job_skills))
        missing_skills = list(set(job_skills) - set(matched_skills))
        
        # Calculate match percentage using skills matching
        match_percentage = calculate_match_percentage(matched_skills, job_skills)
        
        # Generate suggestions
        suggestions = generate_suggestions(missing_skills, matched_skills)
        
        # Explanation
        explanation = (
            f"The match score is calculated by identifying skills from the job description "
            f"that are also present in the resume. "
            f"There are {len(job_skills)} skills in the job description. "
            f"{len(matched_skills)} of them match the resume, resulting in a {match_percentage}% match. "
            f"Missing skills are those in the job description but not found in the resume."
        )
        
        # Save to database
        analysis = ResumeAnalysis(
            user_id=current_user.id,
            resume_name=filename,
            job_description=job_desc,
            match_score=match_percentage,
            matched_skills=json.dumps(matched_skills),
            missing_skills=json.dumps(missing_skills),
            explanation=explanation
        )
        db.session.add(analysis)
        db.session.commit()
        
        # Clean up uploaded file
        os.remove(file_path)
        
        # Render results
        return render_template('results.html', 
                               match_percentage=match_percentage,
                               matched_skills=matched_skills,
                               missing_skills=missing_skills,
                               explanation=explanation,
                               suggestions=suggestions)
    
    return render_template('analyze.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    """User signup page."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        
        # Validation
        if not name or not email or not password:
            flash('All fields are required.', 'error')
            return redirect(url_for('signup'))
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('signup'))
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return redirect(url_for('signup'))
        
        # Check if user exists
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return redirect(url_for('signup'))
        
        # Create new user
        hashed_password = generate_password_hash(password)
        user = User(name=name, email=email, password=hashed_password)
        db.session.add(user)
        db.session.commit()
        
        flash('Account created successfully! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login page."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        
        # Validation
        if not email or not password:
            flash('Email and password are required.', 'error')
            return redirect(url_for('login'))
        
        # Find user
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid email or password.', 'error')
            return redirect(url_for('login'))
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    """User logout."""
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    """User dashboard with past analyses."""
    analyses = ResumeAnalysis.query.filter_by(user_id=current_user.id).order_by(ResumeAnalysis.created_at.desc()).all()
    return render_template('dashboard.html', analyses=analyses)

@app.route('/delete_analysis/<int:analysis_id>', methods=['POST'])
@login_required
def delete_analysis(analysis_id):
    """Delete a past analysis."""
    analysis = ResumeAnalysis.query.filter_by(id=analysis_id, user_id=current_user.id).first()
    if analysis:
        db.session.delete(analysis)
        db.session.commit()
        flash('Analysis deleted successfully.', 'success')
    return redirect(url_for('dashboard'))

# Create database tables
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
@app.route('/admin')
@login_required
def admin():
    """Admin page to view all users"""
    users = User.query.all()
    analyses = ResumeAnalysis.query.all()
    return render_template('admin.html', users=users, analyses=analyses)
