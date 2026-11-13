"""Fast password hashing for isolated tests only; never use on the web service."""
from .settings import *  # noqa: F403

DEBUG = True
SECURE_SSL_REDIRECT = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
