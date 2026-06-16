Automated Attendance System using Face Recognition 📸

A secure, containerized web application that automates student attendance using face recognition technology. Built with Flask, PostgreSQL, and Docker, featuring a secure 3-role system (Student, Teacher, Super Admin) and verifiable proof-of-attendance.

🚀 Features

Role-Based Access Control: Distinct portals for Students, Teachers, and Super Admins.

Video-Based Enrollment: Captures multiple high-quality face encodings via video for higher accuracy.

Live Attendance: Teachers capture classroom photos to mark attendance instantly.

Security: Email OTP verification for registration and password resets.

Proof of Attendance: Generates and saves annotated images with bounding boxes as audit trails.

Mobile-Ready: Optimized to prioritize the back camera on mobile devices.

Production-Ready: Fully Dockerized with Nginx reverse proxy and HTTPS support.

🛠️ Tech Stack

Backend: Python, Flask, Flask-SQLAlchemy

Database: PostgreSQL (with JSONB support for face encodings)

AI/ML: face_recognition (dlib), OpenCV

Frontend: HTML, JavaScript, Tailwind CSS

Infrastructure: Docker, Docker Compose, Nginx

📋 Prerequisites

Before you begin, ensure you have the following installed on your machine:

Docker Desktop (or Docker Engine + Docker Compose)

Git

⚙️ Installation & Setup

Since this project handles sensitive data (passwords, SSL keys), you must configure a few local files that are not included in this repository.

1. Clone the Repository

git clone [https://github.com/b22ai049/attendance-system-flask.git](https://github.com/b22ai049/attendance-system-flask.git)
cd attendance-system-flask


2. Configure Environment Variables (.env)

Create a file named .env in the root directory. This file holds your database credentials and email settings.

Copy and paste the following into .env:

# --- Database Configuration ---
POSTGRES_USER=myuser
POSTGRES_PASSWORD=mypassword
POSTGRES_DB=attendance_db

# Flask App DB Connection (Must match above)
DB_USER=myuser
DB_PASS=mypassword
DB_NAME=attendance_db
DB_HOST=db

# --- Security ---
SECRET_KEY=super_secret_key_change_this

# --- Email Settings (For OTPs) ---
# Use a Google App Password, NOT your real Gmail password.
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-16-char-app-password


Note: To get a Google App Password, go to your Google Account > Security > 2-Step Verification > App Passwords.

3. Generate SSL Certificates (certs/)

To allow camera access and secure connections (HTTPS), you must generate self-signed certificates.

Create a certs folder in the root directory:

mkdir certs


Run the following command to generate the keys (replace YOUR_IP_ADDRESS with your computer's local Wi-Fi IP, e.g., 192.168.1.10, to allow mobile access):

openssl req -x509 -newkey rsa:4096 -nodes -out certs/cert.pem -keyout certs/key.pem -days 365 -subj "/C=IN/ST=State/L=City/O=Organization/CN=YOUR_IP_ADDRESS"


4. Configure Nginx

Open the nginx/nginx.conf file. Find the lines containing server_name and update them to match the IP address you used in the step above.

server_name 192.168.x.x;  # Replace with your actual Local IP


🚀 Running the Application

Build and Start the Containers:

docker-compose up -d --build


Initialize the Database & Admin:
The first time you run the app, you need to create the Super Admin account manually.

docker-compose exec web python create_teacher.py


Follow the prompts in the terminal to set the Admin Username and Password.

Access the Application:
Open your browser (or mobile phone on the same Wi-Fi) and navigate to:
https://YOUR_IP_ADDRESS (e.g., https://192.168.1.10)

Note: You will see a "Not Safe" security warning because of the self-signed certificate. Click "Advanced" -> "Proceed" to access the site.

📱 Troubleshooting

Camera not opening? Ensure you are using https:// and not http://. Browsers block camera access on insecure connections.

"Entity Too Large" Error? If uploading a video fails, ensure client_max_body_size 50m; is present in your nginx.conf.

Database connection failed? Ensure the .env file variables match exactly.

👥 Contributors

VK Santosh (B22AI049) - Core Logic, Backend, & AI

Yerra Nithin Manoj (B22CS066) - Infrastructure, Docker, & Database
