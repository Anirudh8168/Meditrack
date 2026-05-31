"""
SmartTrack context processors.
Injects WebRTC/TURN configuration into every template so the video call
UI can receive server credentials without exposing them in JS source.
"""
from django.conf import settings


def webrtc_config(request):
    """Passes TURN server config to templates as template variables."""
    return {
        'turn_url':        getattr(settings, 'TURN_URL', ''),
        'turn_username':   getattr(settings, 'TURN_USERNAME', ''),
        'turn_credential': getattr(settings, 'TURN_CREDENTIAL', ''),
    }
