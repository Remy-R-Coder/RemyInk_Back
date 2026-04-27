from pathlib import Path
import os
from decimal import Decimal  # Add this
import environ
from django.core.exceptions import ImproperlyConfigured
from celery.schedules import crontab
from datetime import timedelta
 
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()

# Only read .env if we are NOT in production or if the file exists locally
if not os.getenv('DIGITALOCEAN_APP_ID'): # DO automatically sets this variable
    if os.path.exists(os.path.join(BASE_DIR, '.env')):
        environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

SECRET_KEY = env('SECRET_KEY')
DEBUG = env.bool('DEBUG')
ENVIRONMENT = env('ENVIRONMENT', default='production').lower()
IS_PRODUCTION = ENVIRONMENT == 'production'

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS')
if IS_PRODUCTION and not ALLOWED_HOSTS:
    raise ImproperlyConfigured('ALLOWED_HOSTS must be set in production.')
# Add this to your config/settings.py
PAYSTACK_CALLBACK_URL = env('PAYSTACK_CALLBACK_URL', default='https://remyink-9gqjd.ondigitalocean.app/payment/verify')
PAYSTACK_SECRET_KEY = env('PAYSTACK_SECRET_KEY_LIVE')
PAYSTACK_PUBLIC_KEY = env('PAYSTACK_PUBLIC_KEY_LIVE')
PAYSTACK_WEBHOOK_SECRET = env('PAYSTACK_WEBHOOK_SECRET')
PAYSTACK_INITIALIZE_URL = 'https://api.paystack.co/transaction/initialize'
PAYSTACK_VERIFY_URL = 'https://api.paystack.co/transaction/verify/'

CLIENT_FEE_PERCENTAGE = 0.20
FREELANCER_PAYOUT_PERCENTAGE = 0.80

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=7),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
}

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'daphne',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework_simplejwt.token_blacklist',

    'rest_framework',
    'drf_spectacular',
    'channels',
    'django_celery_beat',
    'django_filters',

    'user_module.apps.UserModuleConfig',
    'jobs.apps.JobsConfig',
    'orders.apps.OrdersConfig',
    'chat.apps.ChatConfig',
    'pay_freelancer.apps.PayFreelancerConfig',
    'payment_gateway',
    'payments',
    'notifications',
]
if DEBUG:
    INSTALLED_APPS.append('django_extensions')

ASGI_APPLICATION = "config.asgi.application"
WSGI_APPLICATION = 'config.wsgi.application'

CHANNEL_REDIS_URL = env('CHANNEL_REDIS_URL', default='redis://127.0.0.1:6379/1')

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [CHANNEL_REDIS_URL],
        },
    },
}

AUTH_USER_MODEL = 'user_module.User'
AUTHENTICATION_BACKENDS = ['django.contrib.auth.backends.ModelBackend']

CELERY_BROKER_URL = env('CELERY_BROKER_URL')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = env('TIME_ZONE')
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND')


CELERY_BEAT_SCHEDULE = {
    'check-and-process-auto-payouts': {
        'task': 'pay_freelancer.tasks.check_and_process_auto_payouts',
        'schedule': crontab(minute='0', hour='0'),
        'args': (),
        'options': {'queue': 'remyink_payouts'},
    },
}

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

def _csv_env_list(key: str) -> list[str]:
    raw = env(key, default="")
    return [item.strip() for item in str(raw).split(",") if item.strip()]


CORS_ALLOWED_ORIGINS = _csv_env_list('CORS_ALLOWED_ORIGINS')
CSRF_TRUSTED_ORIGINS = _csv_env_list('CSRF_TRUSTED_ORIGINS')
CORS_ALLOWED_ORIGIN_REGEXES = _csv_env_list('CORS_ALLOWED_ORIGIN_REGEXES')
CORS_ALLOW_CREDENTIALS = env.bool('CORS_ALLOW_CREDENTIALS', default=True)
CORS_ALLOW_ALL_ORIGINS = env.bool('CORS_ALLOW_ALL_ORIGINS', default=False)
if IS_PRODUCTION and CORS_ALLOW_ALL_ORIGINS:
    raise ImproperlyConfigured('CORS_ALLOW_ALL_ORIGINS cannot be True in production.')
if IS_PRODUCTION and not CORS_ALLOW_ALL_ORIGINS and CORS_ALLOW_CREDENTIALS:
    if not CORS_ALLOWED_ORIGINS and not CORS_ALLOWED_ORIGIN_REGEXES:
        raise ImproperlyConfigured(
            'Set CORS_ALLOWED_ORIGINS or CORS_ALLOWED_ORIGIN_REGEXES for credentialed CORS in production.'
        )
if IS_PRODUCTION and not CSRF_TRUSTED_ORIGINS:
    raise ImproperlyConfigured('CSRF_TRUSTED_ORIGINS must be set in production.')

ROOT_URLCONF = 'config.urls'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication', # Add this for guest sessions
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
        'chat_anon': '6000/hour',
        'chat_user': '20000/hour',
        'orders_anon': '2000/hour',
        'orders_user': '10000/hour',
    },
    'DEFAULT_FILTER_BACKENDS': ['django_filters.rest_framework.DjangoFilterBackend'],
}

CACHES = {
    "default": env.cache('CACHE_URL'),
}

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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

SPECTACULAR_SETTINGS = {
    'TITLE': 'RemyInk API',
    'DESCRIPTION': 'API documentation for the RemyInk freelance platform',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SWAGGER_UI_SETTINGS': {
        'deepLinking': True,
        'persistAuthorization': True,
        'displayRequestDuration': True,
    },
    'COMPONENT_SPLIT_REQUEST': True,
    'ENUM_NAME_OVERRIDES': {},
    'POSTPROCESSING_HOOKS': [],
}

DATABASES = {
    'default': env.db('DATABASE_URL'),
}

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

LANGUAGE_CODE = 'en-us'

TIME_ZONE = env('TIME_ZONE')

USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
STATICFILES_DIRS = [STATIC_DIR] if os.path.isdir(STATIC_DIR) else []
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOG_LEVEL = env('LOG_LEVEL', default='INFO')
LOG_TO_FILE = env.bool('LOG_TO_FILE', default=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': LOG_LEVEL,
            'class': 'logging.StreamHandler',
            'formatter': 'simple'
        },
        'file_general': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(BASE_DIR, 'logs', 'general.log'),
            'maxBytes': 1024*1024*5,
            'backupCount': 5,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file_general'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'pay_freelancer': {
            'handlers': ['console', 'file_general'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'celery': {
            'handlers': ['console', 'file_general'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        '': {
            'handlers': ['console', 'file_general'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
    },
    'root': {
        'handlers': ['console', 'file_general'],
        'level': LOG_LEVEL,
    },
}
if not LOG_TO_FILE:
    for logger_name in ('django', 'pay_freelancer', 'celery', ''):
        handlers = LOGGING['loggers'][logger_name]['handlers']
        LOGGING['loggers'][logger_name]['handlers'] = [h for h in handlers if h != 'file_general']
    LOGGING['root']['handlers'] = [h for h in LOGGING['root']['handlers'] if h != 'file_general']
else:
    LOGS_DIR = os.path.join(BASE_DIR, 'logs')
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)


EMAIL_BACKEND = env('EMAIL_BACKEND')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL')
EMAIL_HOST = env('EMAIL_HOST')
EMAIL_PORT = env.int('EMAIL_PORT')
EMAIL_HOST_USER = env('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS')
EMAIL_USE_SSL = env.bool('EMAIL_USE_SSL')
if EMAIL_USE_TLS and EMAIL_USE_SSL:
    raise ImproperlyConfigured('EMAIL_USE_TLS and EMAIL_USE_SSL cannot both be True.')

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = env('SECURE_REFERRER_POLICY', default='strict-origin-when-cross-origin')
X_FRAME_OPTIONS = env('X_FRAME_OPTIONS', default='DENY')
USE_X_FORWARDED_HOST = env.bool('USE_X_FORWARDED_HOST', default=True)
if env.bool('USE_X_FORWARDED_PROTO', default=True):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=not DEBUG)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=not DEBUG)
SESSION_COOKIE_HTTPONLY = env.bool('SESSION_COOKIE_HTTPONLY', default=True)
CSRF_COOKIE_HTTPONLY = env.bool('CSRF_COOKIE_HTTPONLY', default=False)
SESSION_COOKIE_SAMESITE = env('SESSION_COOKIE_SAMESITE', default='None' if not DEBUG else 'Lax')
CSRF_COOKIE_SAMESITE = env('CSRF_COOKIE_SAMESITE', default='None' if not DEBUG else 'Lax')
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=not DEBUG)
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=31536000 if not DEBUG else 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=not DEBUG)
SECURE_HSTS_PRELOAD = env.bool('SECURE_HSTS_PRELOAD', default=not DEBUG)
# Exchange rate: 1 USD to KES
KES_USD_EXCHANGE_RATE = Decimal('130.00')