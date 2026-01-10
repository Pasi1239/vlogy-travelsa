import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_dance.contrib.google import make_google_blueprint, google
from google import genai 
from dotenv import load_dotenv
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import vercel_blob

# --- 1. DYNAMIC ENVIRONMENT LOADING ---
base_dir = Path(__file__).resolve().parent
env_path = base_dir / '.env'
load_dotenv(dotenv_path=env_path)

app = Flask(__name__)

# Allows Google login to work on local computer (http://127.0.0.1)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# --- 2. CONFIGURATION ---
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "travel_secret_123")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

# --- DATABASE LOGIC ---
# This looks for the Vercel Postgres URL first
database_url = os.environ.get("POSTGRES_URL")
# Fix: SQLAlchemy requires 'postgresql://', but Vercel/Neon often gives 'postgres://'
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

# If POSTGRES_URL exists, use it. Otherwise, use local SQLite.
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or f'sqlite:///{base_dir / "vlog.db"}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Use /tmp for uploads on Vercel to avoid "Read-only" errors
app.config['UPLOAD_FOLDER'] = '/tmp/uploads'

db = SQLAlchemy(app)

# --- 3. DEFINE MODEL ---
class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    filename = db.Column(db.String(100))
    desc = db.Column(db.Text)

# Create Database and Folders safely
with app.app_context():
    db.create_all()
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- 4. GOOGLE OAUTH CONFIG ---
blueprint = make_google_blueprint(
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    scope=[
        "openid", 
        "https://www.googleapis.com/auth/userinfo.email", 
        "https://www.googleapis.com/auth/userinfo.profile"
    ],
    offline=True
)
app.register_blueprint(blueprint, url_prefix="/login")

# --- 5. AI CONFIG ---
client = None
if GEMINI_KEY:
    try:
        client = genai.Client(api_key=GEMINI_KEY)
    except Exception as e:
        print(f"AI Initialization failed: {e}")

# --- 6. ROUTES ---
@app.route('/')
def home():
    if not session.get('user') and google.authorized:
        try:
            resp = google.get("/oauth2/v1/userinfo")
            if resp.ok: 
                session['user'] = resp.json()['email']
        except: 
            session.clear()
    
    all_posts = Post.query.all()
    return render_template('index.html', posts=all_posts)

@app.route('/logout')
def logout():
    session.clear() 
    return redirect(url_for('home'))

@app.route('/upload', methods=['POST'])
def upload():
    file = request.files.get('file')
    if file and session.get('user'):
        filename = file.filename
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        new_post = Post(
            title=request.form.get('title'), 
            filename=filename, 
            desc=request.form.get('desc')
        )
        db.session.add(new_post)
        db.session.commit()
    return redirect(url_for('home'))

@app.route('/chat', methods=['POST'])
def chat():
    if not client:
        return jsonify({"reply": "Vlogy is resting today. Check your API key!"})

    try:
        user_msg = request.json.get("message")
        all_posts = Post.query.all()
        posts_info = "\n".join([f"- {p.title}: {p.desc}" for p in all_posts])
        prompt = f"You are 'Vlogy', a travel assistant. Context:\n{posts_info}\nUser: {user_msg}"
        
        response = client.models.generate_content(
            model='gemini-2.0-flash', 
            contents=prompt
        )
        return jsonify({"reply": response.text})
    except Exception as e:
        return jsonify({"reply": "I'm having trouble thinking right now!"})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
@app.route('/upload', methods=['POST'])
def upload():
    # 1. Get data from the form
    # Note: Use 'file' or 'image' depending on your index.html <input name="...">
    file = request.files.get('file') or request.files.get('image')
    title = request.form.get('title')
    desc = request.form.get('desc')

    if file and session.get('user'):
        try:
            # 2. Upload directly to Vercel Blob
            blob = vercel_blob.put(file.filename, file.read(), {'access': 'public'})
            
            # 3. Save to Postgres using the BLOB URL
            new_post = Post(
                title=title, 
                filename=blob.url, # This is the permanent cloud link
                desc=desc
            )
            db.session.add(new_post)
            db.session.commit()
        except Exception as e:
            print(f"Upload failed: {e}")
            
    return redirect(url_for('home'))

@app.route('/chat', methods=['POST'])
def chat():
    if not client:
        return jsonify({"reply": "Vlogy is resting today. Check your API key!"})
    try:
        user_msg = request.json.get("message")
        all_posts = Post.query.all()
        posts_info = "\n".join([f"- {p.title}: {p.desc}" for p in all_posts])
        prompt = f"You are 'Vlogy', a travel assistant. Context:\n{posts_info}\nUser: {user_msg}"
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        return jsonify({"reply": response.text})
    except Exception as e:
        return jsonify({"reply": "I'm having trouble thinking right now!"})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
