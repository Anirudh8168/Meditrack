from django.contrib import admin
from .models import CaregiverProfile, CaregiverPatientAssignment, PatientCaregiverRecord, HospitalCaregiverAssignment

admin.site.register(CaregiverProfile)
admin.site.register(CaregiverPatientAssignment)
admin.site.register(PatientCaregiverRecord)
admin.site.register(HospitalCaregiverAssignment)
