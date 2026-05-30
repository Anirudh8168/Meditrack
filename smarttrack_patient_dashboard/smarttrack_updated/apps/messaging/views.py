from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q, Max
from django.utils import timezone
from .models import Message
from apps.accounts.models import CustomUser
from apps.connections.models import DoctorPatientConnection
from apps.profiles.models import DoctorProfile, PatientProfile
from apps.messaging.utils import user_can_message


@login_required
def inbox(request):
    user = request.user
    raw_contacts = []

    if user.role == 'patient':
        conns = DoctorPatientConnection.objects.filter(patient=user, status='accepted')
        raw_contacts = [c.doctor for c in conns]
        # Also add active caregivers
        from apps.caregiver.models import CaregiverPatientAssignment
        care_conns = CaregiverPatientAssignment.objects.filter(patient=user, status='active')
        raw_contacts.extend([cc.caregiver for cc in care_conns])

    elif user.role == 'doctor':
        conns = DoctorPatientConnection.objects.filter(doctor=user, status='accepted')
        raw_contacts = [c.patient for c in conns]

    elif user.role == 'caregiver':
        from apps.caregiver.access import get_active_patient_context
        ctx = get_active_patient_context(request)
        if ctx['caregiver_mode'] and ctx['patient']:
            patient = ctx['patient']
            conns = DoctorPatientConnection.objects.filter(patient=patient, status='accepted')
            raw_contacts = [c.doctor for c in conns]
            from apps.caregiver.models import CaregiverPatientAssignment
            care_conns = CaregiverPatientAssignment.objects.filter(patient=patient, status='active')
            raw_contacts.extend([cc.caregiver for cc in care_conns if cc.caregiver != user])
        else:
            from apps.caregiver.models import CaregiverPatientAssignment
            assignments = CaregiverPatientAssignment.objects.filter(caregiver=user, status='active')
            raw_contacts = [a.patient for a in assignments]
            for a in assignments:
                doc_conns = DoctorPatientConnection.objects.filter(patient=a.patient, status='accepted')
                for dc in doc_conns:
                    if dc.doctor not in raw_contacts:
                        raw_contacts.append(dc.doctor)

    # Annotate contacts with unread count and last message
    contacts = []
    now = timezone.now()
    for contact in raw_contacts:
        unread = Message.objects.filter(sender=contact, receiver=user, is_read=False).count()
        last_msg = Message.objects.filter(
            Q(sender=user, receiver=contact) | Q(sender=contact, receiver=user)
        ).order_by('-created_at').first()

        # Online status logic: online if active in last 5 minutes
        is_online = False
        if contact.last_activity:
            is_online = (now - contact.last_activity).total_seconds() < 300

        # Get profile photo
        photo_url = None
        try:
            if contact.role == 'doctor':
                photo_url = contact.doctor_profile.profile_photo.url if contact.doctor_profile.profile_photo else None
            elif contact.role == 'patient':
                photo_url = contact.patient_profile.profile_photo.url if contact.patient_profile.profile_photo else None
            elif contact.role == 'caregiver':
                photo_url = contact.caregiver_profile.profile_photo.url if contact.caregiver_profile.profile_photo else None
        except Exception:
            pass

        contacts.append({
            'user': contact,
            'unread': unread,
            'last_message': last_msg,
            'photo_url': photo_url,
            'is_online': is_online,
            'last_activity': contact.last_activity,
        })

    # Sort: unread first, then by last message time
    contacts.sort(key=lambda x: (-(x['unread'] > 0), -(x['last_message'].created_at.timestamp() if x['last_message'] else 0)))

    selected_id = request.GET.get('with')
    selected_user = None
    messages_list = []
    selected_photo = None

    message_draft = (request.GET.get('draft') or '').strip()[:2000]

    if selected_id:
        selected_user = get_object_or_404(CustomUser, id=selected_id)
        if not user_can_message(user, selected_user):
            from django.contrib import messages as django_messages
            django_messages.error(request, 'You are not connected with this user for messaging.')
            return redirect('/messages/')
        messages_list = Message.objects.filter(
            Q(sender=user, receiver=selected_user) | Q(sender=selected_user, receiver=user)
        ).order_by('created_at')
        Message.objects.filter(sender=selected_user, receiver=user, is_read=False).update(is_read=True)

        # Get selected user photo
        try:
            if selected_user.role == 'doctor':
                profile = selected_user.doctor_profile
                selected_photo = profile.profile_photo.url if profile.profile_photo else None
            elif selected_user.role == 'patient':
                profile = selected_user.patient_profile
                selected_photo = profile.profile_photo.url if profile.profile_photo else None
            elif selected_user.role == 'caregiver':
                profile = selected_user.caregiver_profile
                selected_photo = profile.profile_photo.url if profile.profile_photo else None
        except Exception:
            pass

    total_unread = Message.objects.filter(receiver=user, is_read=False).count()

    return render(request, 'dashboard/messages.html', {
        'contacts': contacts,
        'selected_user': selected_user,
        'messages_list': messages_list,
        'selected_photo': selected_photo,
        'total_unread': total_unread,
        'message_draft': message_draft,
    })


@login_required
def send_message(request):
    if request.method == 'POST':
        receiver_id = request.POST.get('receiver_id')
        content = request.POST.get('content', '').strip()
        if content and receiver_id:
            receiver = get_object_or_404(CustomUser, id=receiver_id)
            user = request.user

            # Connection Check
            is_authorized = False
            if user.role == 'patient':
                # Connected to doctor or caregiver
                from apps.connections.models import DoctorPatientConnection
                from apps.caregiver.models import CaregiverPatientAssignment
                if (DoctorPatientConnection.objects.filter(doctor=receiver, patient=user, status='accepted').exists() or
                    CaregiverPatientAssignment.objects.filter(caregiver=receiver, patient=user, status='active').exists()):
                    is_authorized = True
            elif user.role == 'doctor':
                # Connected to patient
                from apps.connections.models import DoctorPatientConnection
                if DoctorPatientConnection.objects.filter(doctor=user, patient=receiver, status='accepted').exists():
                    is_authorized = True
            elif user.role == 'caregiver':
                # Connected to patient
                from apps.caregiver.models import CaregiverPatientAssignment
                if CaregiverPatientAssignment.objects.filter(caregiver=user, patient=receiver, status='active').exists():
                    is_authorized = True
                # Or connected to the patient's doctor
                else:
                    assignments = CaregiverPatientAssignment.objects.filter(caregiver=user, patient__id=receiver.id, status='active') # This is wrong, receiver should be the doctor
                    # Correction: Check if this caregiver cares for any patient that the receiver (doctor) also treats
                    from apps.connections.models import DoctorPatientConnection
                    patients = CaregiverPatientAssignment.objects.filter(caregiver=user, status='active').values_list('patient_id', flat=True)
                    if DoctorPatientConnection.objects.filter(doctor=receiver, patient_id__in=patients, status='accepted').exists():
                        is_authorized = True

            if not is_authorized:
                return JsonResponse({'success': False, 'error': 'You are not connected to this user.'})

            msg = Message.objects.create(sender=user, receiver=receiver, content=content)

            # Create notification for receiver
            from apps.notifications.models import Notification
            from apps.notifications.utils import notify_user
            notify_user(
                user=receiver,
                title=f'💬 New message from {user.get_full_name()}',
                message=content[:100] + ('...' if len(content) > 100 else ''),
                notification_type='message',
                priority='high',
                category=f'msg_{msg.id}',
                related_id=msg.id
            )
            return JsonResponse({
                'success': True,
                'id': msg.id,
                'created_at': msg.created_at.strftime('%I:%M %p'),
                'date': msg.created_at.strftime('%b %d'),
            })
    return JsonResponse({'success': False})


@login_required
def get_messages(request, user_id):
    other = get_object_or_404(CustomUser, id=user_id)
    since_id = request.GET.get('since', 0)

    msgs = Message.objects.filter(
        Q(sender=request.user, receiver=other) | Q(sender=other, receiver=request.user)
    ).filter(id__gt=since_id).order_by('created_at')

    # Mark as delivered and read
    Message.objects.filter(sender=other, receiver=request.user, is_delivered=False).update(is_delivered=True)
    msgs.filter(sender=other, receiver=request.user, is_read=False).update(is_read=True)

    data = [{
        'id': m.id,
        'content': m.content,
        'sender_id': m.sender_id,
        'created_at': m.created_at.strftime('%I:%M %p'),
        'date': m.created_at.strftime('%b %d'),
        'is_mine': m.sender == request.user,
        'is_read': m.is_read,
        'is_delivered': m.is_delivered,
    } for m in msgs]
    return JsonResponse({'messages': data})


@login_required
def unread_message_count(request):
    count = Message.objects.filter(receiver=request.user, is_read=False).count()
    return JsonResponse({'unread_count': count})

@login_required
def get_user_status(request, user_id):
    user = get_object_or_404(CustomUser, id=user_id)
    now = timezone.now()
    is_online = False
    if user.last_activity:
        is_online = (now - user.last_activity).total_seconds() < 300

    return JsonResponse({
        'is_online': is_online,
        'last_activity': user.last_activity.strftime('%I:%M %p') if user.last_activity else None
    })
