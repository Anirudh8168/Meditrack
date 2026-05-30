# SmartTrack Healthcare – Full Project

## What's New in This Version

### Caregiver Dashboard (NEW)
- Full Caregiver role: signup, profile setup, dedicated dashboard
- Monitor all assigned patients in one place
- Mark medicines taken on behalf of patients
- Log activities and upload proof for patients
- 7-day adherence chart, risk level per patient
- Hospital & Personal caregiver types supported

### Admin Dashboard (ENHANCED)
- Tabbed: Patients / Doctors / Caregivers / Appointments / Recent Users
- Appointment status breakdown, high-risk patients list
- Today's stats panel, quick admin action buttons

### Signup (UPDATED)
- 3-column role selector: Patient / Doctor / Caregiver

## Setup

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo_data   # seeds all demo users & data
python manage.py runserver
```

## Demo Credentials (after seed_demo_data)

| Role      | Email                               | Password     |
|-----------|-------------------------------------|--------------|
| Admin     | admin@smarttrack.com                | Admin@1234   |
| Doctor    | dr.anil@smarttrack.com              | Doctor@1234  |
| Doctor    | dr.priya@smarttrack.com             | Doctor@1234  |
| Patient   | ravi.patel@patient.com              | Patient@1234 |
| Patient   | sunita.gupta@patient.com            | Patient@1234 |
| Caregiver | neha.caregiver@smarttrack.com       | Care@1234    |
| Caregiver | rajesh.caregiver@smarttrack.com     | Care@1234    |

## Dashboard URLs

| Role      | URL                    |
|-----------|------------------------|
| Patient   | /dashboard/patient/    |
| Doctor    | /dashboard/doctor/     |
| Caregiver | /dashboard/caregiver/  |
| Admin     | /dashboard/admin/      |
| Django Admin | /admin/            |
