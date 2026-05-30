# SmartTrack - Healthcare Management System
## Setup & Run Instructions

### Quick Start (3 steps)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run migrations
python manage.py migrate

# 3. Seed demo data & start server
python manage.py seed_demo_data
python manage.py runserver
```

Open: http://127.0.0.1:8000

---

## Demo Login Credentials

| Role | Username | Password |
|------|----------|----------|
| Doctor | dr_sharma | demo@1234 |
| Doctor | dr_patel | demo@1234 |
| Doctor | dr_mehta | demo@1234 |
| Patient | patient_raj | demo@1234 |
| Patient | patient_priya | demo@1234 |
| Patient | patient_arun | demo@1234 |
| Caregiver | caregiver_demo | demo@1234 |

---

## Features Implemented

### ✅ 1. 3-Stage Profile Completion
- Patient: Personal Info → Medical Info → Emergency & Lifestyle
- Doctor: Personal Info → Professional Details → Hospital & Settings  
- Caregiver: Personal Info → Caregiver Info → Patient Monitoring
- Step indicators, auto BMI/age calculation, photo upload

### ✅ 2. Caregiver-Patient Connection System
- Caregiver searches patient by ID/phone/name
- Sends connection request → Patient accepts/rejects
- Permission levels: View Only, Reminder Access, Full Access
- Caregiver can mark medicines on behalf of patient
- Patient sees pending caregiver requests on dashboard

### ✅ 3. Medicine Reminder System (Strict Logic)
- **Mark as Taken is DISABLED** until medicine time (±5 to 60 min window)
- Overdose protection: blocks extra doses beyond daily prescription
- Auto-deactivates medicines when course ends
- Repeated reminders every 30s until taken
- Sound alert + popup when medicine time arrives
- History: Active, Expired, Missed tracking

### ✅ 4. Medicine Stock Alerts
- Low stock warning on dashboard
- Critical stock popup notification
- Nearby pharmacy finder (Google Maps API or fallback)

### ✅ 5. Nearby Help Finder
- Built-in pharmacy/clinic finder
- Google Maps integration with fallback

### ✅ 6. Health Risk Analysis
- Auto-calculated risk score based on missed doses
- Consecutive miss streak tracking
- Visual risk level: Low/Medium/High/Critical

### ✅ 7. Appointment System
- Book appointment with doctor
- Doctor approve/reject/cancel
- Video consultation booking

### ✅ 8. Real-time Notifications
- Polling every 15 seconds
- Popup notification for new messages/alerts
- Unread message badge in header
- Sound alert for messages

### ✅ 9. Dashboard Widget Redirections
- All stat cards redirect correctly
- Medicines count → /medicines/
- Compliance → /medicines/analytics/
- Doctors → /connections/list/
- Appointments → /appointments/

### ✅ 10. Demo Data
- 3 doctors, 5 patients, 1 caregiver
- Connected with medicines, logs, appointments

---

## Google Maps API (Optional)
To enable nearby pharmacy search:
1. Get API key from https://console.cloud.google.com
2. Add to smarttrack/settings.py:
   ```python
   GOOGLE_MAPS_API_KEY = 'your-key-here'
   ```
3. Enable: Places API, Maps JavaScript API, Geocoding API

Without API key: fallback to Google Maps search link.
