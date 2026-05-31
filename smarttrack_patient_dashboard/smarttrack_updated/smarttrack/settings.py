from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Security ────────────────────────────────────────────────────────────────
# In production: set SECRET_KEY env var on Render to a long random string.
SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-smarttrack-v2-change-in-production-abc123xyz789')

DEBUG = os.environ.get('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '*').split(',')

# ── Apps ─────────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',               # django-cors-headers (already in requirements.txt)
    'apps.accounts',
    'apps.profiles.apps.ProfilesConfig',
    'apps.connections',
    'apps.medicines',
    'apps.appointments.apps.AppointmentsConfig',
    'apps.messaging',
    'apps.reports',
    'apps.notifications',
    'apps.dashboard',
    'apps.caregiver',
    'apps.family',
    'apps.payments',
    'apps.system_admin',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # static files in production
    'corsheaders.middleware.CorsMiddleware',        # must be before CommonMiddleware
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.accounts.middleware.ActivityMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'smarttrack.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.notifications.context_processors.notification_context',
                'apps.caregiver.context_processors.caregiver_mode_context',
                'apps.dashboard.sidebar.sidebar_active_context',
                # Pass TURN config to all templates
                'smarttrack.context_processors.webrtc_config',
            ],
        },
    },
]

WSGI_APPLICATION = 'smarttrack.wsgi.application'

# ── Database ─────────────────────────────────────────────────────────────────
DATABASES = {
    'default': {
        'ENGINE': os.environ.get('DB_ENGINE', 'django.db.backends.sqlite3'),
        'NAME': os.environ.get('DB_NAME', str(BASE_DIR / 'db.sqlite3')),
        'USER': os.environ.get('DB_USER', ''),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', ''),
        'PORT': os.environ.get('DB_PORT', '3306'),
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        } if os.environ.get('DB_ENGINE') == 'django.db.backends.mysql' else {
            'timeout': 30,
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = False
USE_L10N = True
USE_TZ = True

# ── Static files ─────────────────────────────────────────────────────────────
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
# WhiteNoise: serve compressed static files in production
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'accounts.CustomUser'

LOGIN_URL = '/auth/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
SESSION_COOKIE_AGE = 86400

# ── CSRF — critical for production on Render ─────────────────────────────────
# Add your Render URL here. Replace <your-app> with your actual Render subdomain.
CSRF_TRUSTED_ORIGINS = [
    'https://*.onrender.com',
    'https://*.render.com',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]
# If RENDER_EXTERNAL_HOSTNAME env var is set by Render, add it automatically.
_render_host = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '')
if _render_host:
    CSRF_TRUSTED_ORIGINS.append(f'https://{_render_host}')
    if _render_host not in ALLOWED_HOSTS and ALLOWED_HOSTS != ['*']:
        ALLOWED_HOSTS.append(_render_host)

# ── HTTPS / Proxy settings for Render (runs behind a load balancer) ──────────
# Render terminates SSL at the proxy level; Django must trust the X-Forwarded-Proto header.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

if not DEBUG:
    # Cookies only sent over HTTPS
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # HSTS: tell browsers to only use HTTPS (1 year)
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # Redirect HTTP → HTTPS (Render handles this, but Django can too)
    SECURE_SSL_REDIRECT = False  # Let Render handle SSL redirect to avoid redirect loops
    # Content security
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    X_FRAME_OPTIONS = 'DENY'

# ── CORS ─────────────────────────────────────────────────────────────────────
# Allow same-origin requests and any Render subdomains (for future API use)
CORS_ALLOWED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]
CORS_ALLOW_CREDENTIALS = True
CORS_URLS_REGEX = r'^/api/.*$'  # Only apply CORS to /api/ routes

# ── WebRTC TURN server configuration ─────────────────────────────────────────
# Set these on Render (Environment Variables) for a production TURN server.
# Without TURN, WebRTC fails when users are behind NAT (mobile networks, office networks).
#
# Option A — Free: https://www.metered.ca/tools/openrelay/ (limited bandwidth)
# Option B — Paid: https://metered.ca  (~$0.40/GB, very affordable)
# Option C — Self-hosted: coturn on a VPS (cheapest at scale)
#
# Leave blank to use the built-in public Open Relay fallback in webrtc_consultation.js
TURN_URL        = os.environ.get('TURN_URL', '')
TURN_USERNAME   = os.environ.get('TURN_USERNAME', '')
TURN_CREDENTIAL = os.environ.get('TURN_CREDENTIAL', '')

# Razorpay (set in environment for production)
RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET', '')
