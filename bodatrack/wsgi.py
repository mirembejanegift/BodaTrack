"""WSGI entry point for BodaTrack."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bodatrack.settings")

application = get_wsgi_application()
