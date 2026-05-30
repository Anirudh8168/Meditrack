from django.utils import timezone
from apps.accounts.models import CustomUser


class ActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            CustomUser.objects.filter(id=request.user.id).update(last_activity=timezone.now())

        response = self.get_response(request)
        return response
