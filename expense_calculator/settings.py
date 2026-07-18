"""
Django settings for expense_calculator project.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/topics/settings/
"""
import os
import sys
import logging
from dotenv import load_dotenv
from pathlib import Path


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# SECURITY: Environment-based settings
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
DEBUG = ENVIRONMENT == "development"
SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "django-insecure-dev-key-only-for-development"
    if DEBUG
    else None
)

if not SECRET_KEY or SECRET_KEY.startswith("django-insecure"):
    if not DEBUG:
        raise ValueError("SECRET_KEY must be set in environment for production")

# SECURITY: Restrict allowed hosts
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,django").split(",")
ALLOWED_HOSTS = [host.strip() for host in ALLOWED_HOSTS]

# SECURITY: Configure CSRF and CORS
CSRF_TRUSTED_ORIGINS = [
    host.strip() for host in os.getenv(
        "CSRF_TRUSTED_ORIGINS", 
        "http://localhost,http://127.0.0.1"
    ).split(",")
]

CORS_ALLOWED_ORIGINS = [
    host.strip() for host in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://localhost:5173"
    ).split(",")
] if not DEBUG else ["*"]

# SECURITY: HTTPS and SSL configuration
SECURE_SSL_REDIRECT = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# SECURITY: HSTS (HTTP Strict Transport Security)
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0" if DEBUG else "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG

# SECURITY: Additional security headers
SECURE_CONTENT_SECURITY_POLICY = {
    "default-src": ("'self'",),
    "script-src": ("'self'", "'unsafe-inline'", "cdn.jsdelivr.net", "cdn.jsdelivr.net"),
    "style-src": ("'self'", "'unsafe-inline'", "cdn.jsdelivr.net"),
    "img-src": ("'self'", "data:"),
} if not DEBUG else {}

X_FRAME_OPTIONS = "DENY"
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# API Keys (never commit to version control)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'expense',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'expense_calculator.middleware.SecurityHeadersMiddleware',
    'expense_calculator.middleware.ErrorHandlingMiddleware',
]

ROOT_URLCONF = 'expense_calculator.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            BASE_DIR / "templates"
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


WSGI_APPLICATION = 'expense_calculator.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB"),
        "USER": os.getenv("POSTGRES_USER"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD"),
        "HOST": os.getenv("POSTGRES_HOST"),
        "PORT": os.getenv("POSTGRES_PORT"),
        "OPTIONS": {
            "options": "-c search_path=expense"
        },
        "CONN_MAX_AGE": int(os.getenv("DATABASE_CONN_MAX_AGE", "600")),
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / "static",
]
STATIC_ROOT = '/app/staticfiles'

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Create logs directory and configure log levels
LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(parents=True, exist_ok=True)
APP_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ============================================================
# LOGGING CONFIGURATION
# ============================================================

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            '()': 'expense.logging_utils.ContextAwareFormatter',
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            '()': 'expense.logging_utils.ContextAwareFormatter',
            'format': '{levelname} {asctime} {message}',
            'style': '{',
        },
    },
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse',
        },
        'require_debug_true': {
            '()': 'django.utils.log.RequireDebugTrue',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'app_file': {
            'level': APP_LOG_LEVEL,
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'application.log',
            'maxBytes': 1024 * 1024 * 10,  # 10MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'mail_admins': {
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler',
            'include_html': True,
        }
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'app_file'],
            'level': APP_LOG_LEVEL,
            'propagate': False,
        },
        'expense': {
            'handlers': ['console', 'app_file'],
            'level': APP_LOG_LEVEL,
            'propagate': False,
        },
        'expense.views': {
            'handlers': ['console', 'app_file'],
            'level': APP_LOG_LEVEL,
            'propagate': False,
        },
        'expense.api_views': {
            'handlers': ['console', 'app_file'],
            'level': APP_LOG_LEVEL,
            'propagate': False,
        },
        'expense.services': {
            'handlers': ['console', 'app_file'],
            'level': APP_LOG_LEVEL,
            'propagate': False,
        },
        'expense.validators': {
            'handlers': ['console', 'app_file'],
            'level': APP_LOG_LEVEL,
            'propagate': False,
        },
        'expense_calculator.middleware': {
            'handlers': ['console', 'app_file'],
            'level': APP_LOG_LEVEL,
            'propagate': False,
        },
        'django.request': {
            'handlers': ['app_file', 'mail_admins'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['app_file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# ============================================================
# FILE UPLOAD SECURITY
# ============================================================

# Maximum file size: 10MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# Allowed file types for uploads
ALLOWED_UPLOAD_EXTENSIONS = ['csv', 'png', 'jpg', 'jpeg']
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB

# ============================================================
# CACHE CONFIGURATION
# ============================================================

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'expense-calculator-cache',
        'OPTIONS': {
            'MAX_ENTRIES': 1000
        } if DEBUG else {
            'MAX_ENTRIES': 10000
        }
    }
}

# Test fallback: use local SQLite when running Django tests unless explicitly disabled.
if "test" in sys.argv and os.getenv("USE_SQLITE_TEST_FALLBACK", "1") == "1":
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "test_db.sqlite3",
    }