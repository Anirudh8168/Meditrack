from functools import wraps
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def admin_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if user.role != 'admin' and not user.is_superuser:
            return redirect('system_admin_login')
        if not user.is_active:
            return redirect('system_admin_login')
        return view_func(request, *args, **kwargs)
    return wrapper
