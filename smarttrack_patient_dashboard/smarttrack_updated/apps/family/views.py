from datetime import date

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .models import FamilyMember
from apps.accounts.models import CustomUser
from apps.notifications.models import Notification
from apps.notifications.notification_utils import notifications_in_date_range
from apps.medicines.risk_alert_service import get_alerts_for_user
from django.db.models import Q

@login_required
def family_dashboard(request):
    user = request.user
    # Family members see their linked patients and alerts
    if user.role == 'family':
        # Find all patients linked to this user
        family_links = FamilyMember.objects.filter(user=user)
        patients = [link.patient for link in family_links]

        today = date.today()
        notifications = notifications_in_date_range(
            Notification.objects.filter(user=user, notification_type='alert'),
            today,
            today,
        ).order_by('-created_at')

        return render(request, 'dashboard/family/index.html', {
            'patients': patients,
            'notifications': notifications,
            'risk_alerts': get_alerts_for_user(user, limit=15),
            'today': today,
        })
    else:
        return redirect('/dashboard/')

@login_required
def manage_family(request):
    # Only patients can manage their family members
    if request.user.role != 'patient':
        return redirect('/dashboard/')

    patient = request.user
    family_members = FamilyMember.objects.filter(patient=patient)

    if request.method == 'POST':
        name = request.POST.get('name')
        relation = request.POST.get('relation')
        phone = request.POST.get('phone')
        email = request.POST.get('email')
        user_id = request.POST.get('user_id')
        is_emergency = request.POST.get('is_emergency') == 'on'

        user = None
        if user_id:
            try:
                user = CustomUser.objects.get(id=user_id)
            except CustomUser.DoesNotExist:
                pass

        FamilyMember.objects.create(
            patient=patient,
            user=user,
            name=name,
            relation=relation,
            phone=phone,
            email=email,
            is_emergency_contact=is_emergency
        )
        return redirect('manage_family')

    return render(request, 'dashboard/family/manage.html', {
        'family_members': family_members,
    })

@login_required
def remove_family_member(request, member_id):
    if request.user.role != 'patient':
        return redirect('/dashboard/')

    member = get_object_or_404(FamilyMember, id=member_id, patient=request.user)
    member.delete()
    return redirect('manage_family')

@login_required
def mark_alert_read(request, notif_id):
    notif = get_object_or_404(Notification, id=notif_id, user=request.user)
    notif.is_read = True
    notif.save()
    return JsonResponse({'success': True})
