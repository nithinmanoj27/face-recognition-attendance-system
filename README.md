#  Face Recognition Attendance System

A secure, containerized web application that automates student attendance using face recognition technology. Built using Flask, PostgreSQL, OpenCV, and Docker, the system provides secure role-based access control, live attendance marking, and verifiable proof-of-attendance generation.

---

##  Features

-  Role-Based Access Control (RBAC) with separate portals for Students, Teachers, and Super Admins.
-  Video-based facial enrollment for improved recognition accuracy.
-  Live attendance marking using classroom image capture.
-  Email OTP verification for registration and password resets.
-  Automated proof-of-attendance generation with annotated images.
-  Mobile-friendly interface with optimized camera support.
-  Dockerized deployment with Nginx reverse proxy and HTTPS support.

---

##  Tech Stack

| Category | Technologies |
|----------|--------------|
| Backend | Python, Flask, Flask-SQLAlchemy |
| Database | PostgreSQL (JSONB) |
| Computer Vision | OpenCV, dlib, face_recognition |
| Frontend | HTML, JavaScript, Tailwind CSS |
| Infrastructure | Docker, Docker Compose, Nginx |

---

##  Project Structure

```text
attendance-system-flask/

├── app.py
├── create_teacher.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── nginx/
├── static/
├── templates/
└── README.md
```

---

##  Prerequisites

Install the following before running the project:

- Docker Desktop (or Docker Engine + Docker Compose)
- Git

---

##  Installation & Setup

### 1️ Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/face-recognition-attendance-system.git

cd face-recognition-attendance-system
```

### 2️ Configure environment variables

Create a `.env` file in the root directory.

```env
POSTGRES_USER=myuser
POSTGRES_PASSWORD=mypassword
POSTGRES_DB=attendance_db

DB_USER=myuser
DB_PASS=mypassword
DB_NAME=attendance_db
DB_HOST=db

SECRET_KEY=your_secret_key

MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-google-app-password
```

---

### 3️ Generate SSL certificates

Create a `certs` folder.

```bash
mkdir certs
```

Generate certificates.

```bash
openssl req -x509 -newkey rsa:4096 -nodes \
-out certs/cert.pem \
-keyout certs/key.pem \
-days 365 \
-subj "/C=IN/ST=State/L=City/O=Organization/CN=YOUR_LOCAL_IP"
```

---

### 4️ Configure Nginx

Open:

```text
nginx/nginx.conf
```

Update:

```nginx
server_name YOUR_LOCAL_IP;
```

Example:

```nginx
server_name 192.168.1.10;
```

---

##  Running the Application

Build and start the containers.

```bash
docker-compose up -d --build
```

Create the Super Admin account.

```bash
docker-compose exec web python create_teacher.py
```

Open the application.

```text
https://YOUR_LOCAL_IP
```

Example:

```text
https://192.168.1.10
```

>  Browsers will show a security warning because a self-signed certificate is used. Click **Advanced → Proceed**.

---

##  Troubleshooting

### Camera not opening?

Use `https://` instead of `http://`.

### Video upload failing?

Ensure:

```nginx
client_max_body_size 50m;
```

is present inside `nginx.conf`.

### Database connection failed?

Verify that all `.env` variables match correctly.

---

## 👥 Contributors

- Yerra Nithin Manoj (B22CS066)
- VK Santosh (B22AI049)
