# 🚀 PropFlow MVP - Complete API Documentation

**Version:** 1.0.0  
**Base URL:** `http://localhost:8000/api`  
**Authentication:** JWT Bearer Token

---

## 📋 Table of Contents

1. [Authentication](#authentication)
2. [User Management](#user-management)
3. [Tenant/Client Management](#tenant-client-management)
4. [People Hub (Residents)](#people-hub-residents)
5. [CSV Upload System](#csv-upload-system)
6. [Properties Management](#properties-management)
7. [Roles & Permissions](#roles--permissions)
8. [Dashboard & Analytics](#dashboard--analytics)

---

## 🔐 Authentication

### 1. Register User
**Endpoint:** `POST /api/accounts/register/`  
**Access:** Public  
**Description:** Register a new user account

**Request Body:**
```json
{
  "username": "john_doe",
  "email": "john@example.com",
  "password": "SecurePass123!",
  "password2": "SecurePass123!",
  "first_name": "John",
  "last_name": "Doe",
  "phone": "+1234567890",
  "role": "tenant"
}
```

**Response (201):**
```json
{
  "user": {
    "id": "uuid",
    "username": "john_doe",
    "email": "john@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "role": "tenant",
    "is_active": true,
    "is_approved": false,
    "email_verified": false
  },
  "access": "eyJ0eXAiOiJKV1QiLCJh...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJh..."
}
```

---

### 2. Login
**Endpoint:** `POST /api/accounts/login/`  
**Access:** Public  
**Description:** Login and get JWT tokens

**Request Body:**
```json
{
  "username": "john_doe",
  "password": "SecurePass123!"
}
```

**Response (200):**
```json
{
  "user": {
    "id": "uuid",
    "username": "john_doe",
    "email": "john@example.com",
    "full_name": "John Doe",
    "role": "tenant"
  },
  "access": "eyJ0eXAiOiJKV1QiLCJh...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJh...",
  "tenant": {
    "id": "uuid",
    "name": "Skyline Properties",
    "domain": "skyline.propflow.com"
  }
}
```

**Error (403):**
```json
{
  "error": "Your account is pending approval from the administrator"
}
```

---

### 3. Refresh Token
**Endpoint:** `POST /api/accounts/token/refresh/`  
**Access:** Public  
**Description:** Get new access token using refresh token

**Request Body:**
```json
{
  "refresh": "eyJ0eXAiOiJKV1QiLCJh..."
}
```

**Response (200):**
```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJh..."
}
```

---

### 4. Request OTP
**Endpoint:** `POST /api/accounts/request-otp/`  
**Access:** Public  
**Description:** Request OTP for email verification or password reset

**Request Body:**
```json
{
  "email": "john@example.com"
}
```

**Response (200):**
```json
{
  "message": "OTP sent to john@example.com",
  "expires_in": 300
}
```

---

### 5. Verify OTP
**Endpoint:** `POST /api/accounts/verify-otp/`  
**Access:** Public  
**Description:** Verify OTP code

**Request Body:**
```json
{
  "email": "john@example.com",
  "otp_code": "123456"
}
```

**Response (200):**
```json
{
  "message": "OTP verified successfully",
  "user": { /* user object */ },
  "access": "eyJ0eXAiOiJKV1QiLCJh...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJh..."
}
```

---

## 👤 User Management

### 6. Get Current User
**Endpoint:** `GET /api/accounts/me/`  
**Access:** Authenticated  
**Headers:** `Authorization: Bearer {access_token}`

**Response (200):**
```json
{
  "user": {
    "id": "uuid",
    "username": "john_doe",
    "email": "john@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "full_name": "John Doe",
    "phone": "+1234567890",
    "role": "tenant",
    "is_active": true,
    "is_approved": true,
    "email_verified": true,
    "avatar": "/media/avatars/john_doe.jpg",
    "unit_number": "101",
    "building_name": "Building A",
    "emergency_contact_name": "Jane Doe",
    "emergency_contact_phone": "+0987654321",
    "profile": {
      "date_of_birth": "1990-01-01",
      "gender": "male",
      "occupation": "Software Engineer",
      "address_line_1": "123 Main St"
    }
  },
  "tenant": {
    "id": "uuid",
    "name": "Skyline Properties",
    "domain": "skyline.propflow.com"
  }
}
```

---

### 7. Update Profile
**Endpoint:** `PUT /api/accounts/profile/`  
**Access:** Authenticated  
**Content-Type:** `multipart/form-data` (if uploading avatar)

**Request Body:**
```json
{
  "first_name": "John",
  "last_name": "Doe",
  "phone": "+1234567890",
  "emergency_contact_name": "Jane Doe",
  "emergency_contact_phone": "+0987654321",
  "profile": {
    "date_of_birth": "1990-01-01",
    "gender": "male",
    "occupation": "Software Engineer"
  }
}
```

**With Avatar:**
```
FormData:
- first_name: John
- last_name: Doe
- avatar: [file]
```

**Response (200):**
```json
{
  "id": "uuid",
  "username": "john_doe",
  "email": "john@example.com",
  "full_name": "John Doe",
  "avatar": "/media/avatars/john_doe.jpg"
}
```

---

### 8. Change Password
**Endpoint:** `POST /api/accounts/change-password/`  
**Access:** Authenticated

**Request Body:**
```json
{
  "old_password": "OldPass123!",
  "new_password": "NewPass123!",
  "new_password2": "NewPass123!"
}
```

**Response (200):**
```json
{
  "message": "Password changed successfully"
}
```

---

### 9. List Users (Admin Only)
**Endpoint:** `GET /api/accounts/users/`  
**Access:** Admin/Staff  
**Query Parameters:**
- `role`: Filter by role (tenant, staff, manager)
- `is_active`: Filter by active status (true/false)
- `is_approved`: Filter by approval status (true/false)
- `search`: Search by name, email, username
- `page`: Page number
- `page_size`: Results per page (default: 20)

**Example:** `GET /api/accounts/users/?role=tenant&is_approved=false&page=1`

**Response (200):**
```json
{
  "count": 50,
  "next": "http://localhost:8000/api/accounts/users/?page=2",
  "previous": null,
  "results": [
    {
      "id": "uuid",
      "username": "john_doe",
      "email": "john@example.com",
      "full_name": "John Doe",
      "role": "tenant",
      "is_active": true,
      "is_approved": false,
      "created_at": "2025-01-15T10:30:00Z"
    }
  ]
}
```

---

### 10. Get User Details
**Endpoint:** `GET /api/accounts/users/{user_id}/`  
**Access:** Admin/Staff

**Response (200):**
```json
{
  "id": "uuid",
  "username": "john_doe",
  "email": "john@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "full_name": "John Doe",
  "phone": "+1234567890",
  "role": "tenant",
  "is_active": true,
  "is_approved": true,
  "email_verified": true,
  "avatar": "/media/avatars/john_doe.jpg",
  "profile": { /* full profile */ },
  "role_assignments": [ /* roles */ ],
  "permissions": ["view_residents", "edit_profile"]
}
```

---

### 11. Update User (Admin Only)
**Endpoint:** `PATCH /api/accounts/users/{user_id}/`  
**Access:** Admin/Staff

**Request Body:**
```json
{
  "is_approved": true,
  "is_active": true,
  "unit_number": "101",
  "building_name": "Building A"
}
```

**Response (200):**
```json
{
  "message": "User updated successfully",
  "user": { /* updated user object */ }
}
```

---

### 12. Delete User (Admin Only)
**Endpoint:** `DELETE /api/accounts/users/{user_id}/`  
**Access:** Admin

**Response (204):** No content

---

## 🏢 Tenant/Client Management

### 13. List Clients (Super Admin Only)
**Endpoint:** `GET /api/tenants/clients/`  
**Access:** Super Admin  
**Query Parameters:**
- `subscription_plan`: Filter by plan (basic, premium, enterprise)
- `is_active`: Filter by status (true/false)
- `search`: Search by name, email

**Response (200):**
```json
{
  "count": 10,
  "results": [
    {
      "id": "uuid",
      "name": "Skyline Properties",
      "schema_name": "skyline",
      "contact_email": "admin@skyline.com",
      "contact_phone": "+1234567890",
      "subscription_plan": "premium",
      "is_active": true,
      "created_on": "2025-01-01T00:00:00Z",
      "domains": [
        {
          "domain": "skyline.propflow.com",
          "is_primary": true
        }
      ],
      "features": {
        "people_hub": true,
        "csv_upload": true,
        "maintenance": true
      }
    }
  ]
}
```

---

### 14. Create Client (Super Admin Only)
**Endpoint:** `POST /api/tenants/clients/`  
**Access:** Super Admin

**Request Body:**
```json
{
  "name": "Golden Gate Communities",
  "schema_name": "goldengate",
  "contact_email": "admin@goldengate.com",
  "contact_phone": "+1234567890",
  "address": "123 Business St, San Francisco, CA",
  "subscription_plan": "premium",
  "domains": [
    {
      "domain": "goldengate.propflow.com",
      "is_primary": true
    }
  ]
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "name": "Golden Gate Communities",
  "schema_name": "goldengate",
  "message": "Client created successfully. Database schema initialized."
}
```

---

### 15. Get Client Details
**Endpoint:** `GET /api/tenants/clients/{client_id}/`  
**Access:** Super Admin

**Response (200):**
```json
{
  "id": "uuid",
  "name": "Skyline Properties",
  "schema_name": "skyline",
  "contact_email": "admin@skyline.com",
  "subscription_plan": "premium",
  "features": { /* all features */ },
  "domains": [ /* domains list */ ],
  "statistics": {
    "total_users": 150,
    "total_properties": 5,
    "total_units": 200,
    "occupied_units": 180
  }
}
```

---

### 16. Update Client Features
**Endpoint:** `PUT /api/tenants/clients/{client_id}/features/`  
**Access:** Super Admin

**Request Body:**
```json
{
  "features": {
    "people_hub": true,
    "csv_upload": true,
    "maintenance": true,
    "payments": false
  }
}
```

**Response (200):**
```json
{
  "features": { /* updated features */ }
}
```

---

### 17. Get Current Tenant Info
**Endpoint:** `GET /api/tenants/current/`  
**Access:** Authenticated

**Response (200):**
```json
{
  "id": "uuid",
  "name": "Skyline Properties",
  "schema_name": "skyline",
  "subscription_plan": "premium",
  "logo": "/media/tenant_logos/skyline.png",
  "features": {
    "people_hub": true,
    "csv_upload": true
  }
}
```

---

### 18. System Statistics (Super Admin Only)
**Endpoint:** `GET /api/tenants/system/stats/`  
**Access:** Super Admin

**Response (200):**
```json
{
  "total_clients": 25,
  "active_clients": 22,
  "total_users": 3500,
  "total_properties": 150,
  "total_units": 5000,
  "monthly_revenue": 125000.00,
  "system_health": "excellent",
  "recent_clients": [ /* last 5 clients */ ]
}
```

---

## 👥 People Hub (Residents)

### 19. List Residents
**Endpoint:** `GET /api/accounts/people-hub/residents/`  
**Access:** Admin/Staff  
**Query Parameters:**
- `search`: Search by name, email, phone
- `building`: Filter by building name
- `unit_number`: Filter by unit
- `is_active`: Filter by status (true/false)
- `is_approved`: Filter by approval (true/false)
- `email_verified`: Filter by verification (true/false)
- `page`: Page number
- `page_size`: Results per page

**Example:** `GET /api/accounts/people-hub/residents/?building=Building A&is_approved=true`

**Response (200):**
```json
{
  "count": 50,
  "next": "...",
  "previous": null,
  "results": [
    {
      "id": "uuid",
      "username": "john_doe",
      "email": "john@example.com",
      "full_name": "John Doe",
      "phone": "+1234567890",
      "unit_number": "101",
      "building_name": "Building A",
      "is_active": true,
      "is_approved": true,
      "email_verified": true,
      "created_at": "2025-01-15T10:30:00Z",
      "profile_completion": 85,
      "lease_status": "active"
    }
  ]
}
```

---

### 20. Create Resident (Manual Entry)
**Endpoint:** `POST /api/accounts/people-hub/residents/`  
**Access:** Admin/Staff

**Request Body:**
```json
{
  "username": "jane_smith",
  "email": "jane@example.com",
  "password": "TempPass123!",
  "first_name": "Jane",
  "last_name": "Smith",
  "phone": "+1234567890",
  "unit_number": "102",
  "building_name": "Building A",
  "emergency_contact_name": "John Smith",
  "emergency_contact_phone": "+0987654321",
  "profile": {
    "date_of_birth": "1985-05-15",
    "gender": "female",
    "occupation": "Teacher"
  }
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "username": "jane_smith",
  "message": "Resident created successfully",
  "credentials": {
    "username": "jane_smith",
    "temporary_password": "TempPass123!"
  }
}
```

---

### 21. Get Resident Details
**Endpoint:** `GET /api/accounts/people-hub/residents/{resident_id}/`  
**Access:** Admin/Staff

**Response (200):**
```json
{
  "id": "uuid",
  "username": "john_doe",
  "email": "john@example.com",
  "full_name": "John Doe",
  "phone": "+1234567890",
  "avatar": "/media/avatars/john_doe.jpg",
  "unit_number": "101",
  "building_name": "Building A",
  "role": "tenant",
  "is_active": true,
  "is_approved": true,
  "email_verified": true,
  "emergency_contact_name": "Jane Doe",
  "emergency_contact_phone": "+0987654321",
  "created_at": "2025-01-15T10:30:00Z",
  "last_login": "2025-10-21T08:30:00Z",
  "profile": {
    "date_of_birth": "1990-01-01",
    "gender": "male",
    "occupation": "Software Engineer",
    "bio": "Long-time resident",
    "household_size": 3,
    "has_pets": true,
    "pet_details": "1 dog - Golden Retriever",
    "vehicle_count": 2,
    "lease_start_date": "2024-01-01",
    "lease_end_date": "2025-12-31",
    "monthly_rent": 2500.00
  },
  "activity_logs": [ /* recent activities */ ]
}
```

---

### 22. Update Resident
**Endpoint:** `PATCH /api/accounts/people-hub/residents/{resident_id}/`  
**Access:** Admin/Staff

**Request Body:**
```json
{
  "unit_number": "103",
  "building_name": "Building B",
  "is_approved": true,
  "phone": "+1234567890"
}
```

**Response (200):**
```json
{
  "message": "Resident updated successfully",
  "resident": { /* updated resident */ }
}
```

---

### 23. Delete Resident
**Endpoint:** `DELETE /api/accounts/people-hub/residents/{resident_id}/`  
**Access:** Admin

**Response (204):** No content

---

### 24. Bulk Approve Residents
**Endpoint:** `POST /api/accounts/people-hub/residents/bulk_action/`  
**Access:** Admin/Staff

**Request Body:**
```json
{
  "resident_ids": [
    "uuid1",
    "uuid2",
    "uuid3"
  ],
  "action": "approve"
}
```

**Actions:** `approve`, `disapprove`, `activate`, `deactivate`, `delete`

**Response (200):**
```json
{
  "message": "Successfully approved 3 residents",
  "success_count": 3,
  "failed_count": 0
}
```

---

### 25. People Hub Statistics
**Endpoint:** `GET /api/accounts/people-hub/stats/`  
**Access:** Admin/Staff

**Response (200):**
```json
{
  "total_residents": 150,
  "active_residents": 140,
  "inactive_residents": 10,
  "approved_residents": 145,
  "pending_approval": 5,
  "verified_emails": 138,
  "with_active_leases": 142,
  "recent_registrations": 8,
  "occupancy_rate": 95.5
}
```

---

### 26. Residents by Building
**Endpoint:** `GET /api/accounts/people-hub/residents-by-building/`  
**Access:** Admin/Staff

**Response (200):**
```json
{
  "buildings": [
    {
      "building_name": "Building A",
      "total_residents": 50,
      "active_residents": 48,
      "occupancy_rate": 96.0
    },
    {
      "building_name": "Building B",
      "total_residents": 45,
      "active_residents": 42,
      "occupancy_rate": 93.3
    }
  ]
}
```

---

### 27. Export Residents to CSV
**Endpoint:** `GET /api/accounts/people-hub/export/`  
**Access:** Admin/Staff  
**Query Parameters:** Same as list residents

**Response (200):** CSV file download
```
Content-Type: text/csv
Content-Disposition: attachment; filename="residents_export_2025-10-21.csv"
```

---

### 28. Residents Directory (Read-Only)
**Endpoint:** `GET /api/accounts/people-hub/directory/`  
**Access:** Authenticated (All users)

**Response (200):**
```json
{
  "residents": [
    {
      "full_name": "John Doe",
      "unit_number": "101",
      "building_name": "Building A",
      "phone": "+1234567890",
      "email": "john@example.com"
    }
  ]
}
```

---

## 📤 CSV Upload System

### 29. Upload CSV File
**Endpoint:** `POST /api/accounts/csv/upload/`  
**Access:** Admin/Staff  
**Content-Type:** `multipart/form-data`

**Request Body:**
```
FormData:
- file: [residents.csv]
- upload_type: "residents"
- auto_approve: false
```

**Response (201):**
```json
{
  "upload_id": "uuid",
  "task_id": "celery-task-id",
  "filename": "residents.csv",
  "upload_type": "residents",
  "status": "pending",
  "message": "File uploaded successfully. Processing started in background."
}
```

---

### 30. Get CSV Upload Status
**Endpoint:** `GET /api/accounts/csv/uploads/{upload_id}/`  
**Access:** Admin/Staff

**Response (200):**
```json
{
  "id": "uuid",
  "original_filename": "residents.csv",
  "upload_type": "residents",
  "status": "processing",
  "total_rows": 100,
  "processed_rows": 45,
  "success_count": 40,
  "error_count": 5,
  "created_at": "2025-10-21T10:00:00Z",
  "processing_started_at": "2025-10-21T10:00:05Z",
  "uploaded_by": {
    "id": "uuid",
    "username": "admin",
    "full_name": "Admin User"
  }
}
```

**Status values:** `pending`, `processing`, `completed`, `failed`, `partial`

---

### 31. Get CSV Processing Results
**Endpoint:** `GET /api/accounts/csv/uploads/{upload_id}/results/`  
**Access:** Admin/Staff

**Response (200):**
```json
{
  "upload_id": "uuid",
  "total_rows": 100,
  "success_count": 95,
  "error_count": 5,
  "results": [
    {
      "row_number": 1,
      "status": "success",
      "data": {
        "username": "john_doe",
        "email": "john@example.com",
        "full_name": "John Doe"
      },
      "user_id": "uuid",
      "message": "User created successfully"
    },
    {
      "row_number": 6,
      "status": "error",
      "data": {
        "username": "jane_doe",
        "email": "invalid-email"
      },
      "errors": {
        "email": ["Enter a valid email address."]
      }
    }
  ]
}
```

---

### 32. List CSV Uploads (History)
**Endpoint:** `GET /api/accounts/csv/uploads/`  
**Access:** Admin/Staff  
**Query Parameters:**
- `status`: Filter by status
- `upload_type`: Filter by type
- `uploaded_by`: Filter by user
- `date_from`: Filter from date
- `date_to`: Filter to date

**Response (200):**
```json
{
  "count": 25,
  "results": [
    {
      "id": "uuid",
      "original_filename": "residents_batch1.csv",
      "upload_type": "residents",
      "status": "completed",
      "total_rows": 100,
      "success_count": 98,
      "error_count": 2,
      "created_at": "2025-10-20T14:30:00Z",
      "uploaded_by": {
        "username": "admin",
        "full_name": "Admin User"
      }
    }
  ]
}
```

---

### 33. Download CSV Template
**Endpoint:** `GET /api/accounts/csv/template/`  
**Access:** Admin/Staff  
**Query Parameters:**
- `upload_type`: Template type (residents, properties)

**Example:** `GET /api/accounts/csv/template/?upload_type=residents`

**Response (200):** CSV file download
```
Content-Type: text/csv
Content-Disposition: attachment; filename="residents_template.csv"

username,email,first_name,last_name,phone,unit_number,building_name,emergency_contact_name,emergency_contact_phone
john_doe,john@example.com,John,Doe,+1234567890,101,Building A,Jane Doe,+0987654321
```

---

### 34. Retry Failed CSV Processing
**Endpoint:** `POST /api/accounts/csv/uploads/{upload_id}/retry/`  
**Access:** Admin/Staff

**Response (200):**
```json
{
  "message": "Processing restarted",
  "task_id": "new-celery-task-id",
  "status": "pending"
}
```

---

### 35. Delete CSV Upload
**Endpoint:** `DELETE /api/accounts/csv/uploads/{upload_id}/`  
**Access:** Admin

**Response (204):** No content

---

## 🏠 Properties Management

### 36. List Buildings
**Endpoint:** `GET /api/properties/buildings/`  
**Access:** Admin/Staff  
**Query Parameters:**
- `search`: Search by name, address
- `property_type`: Filter by type
- `page`: Page number

**Response (200):**
```json
{
  "count": 5,
  "results": [
    {
      "id": "uuid",
      "name": "Building A",
      "address": "123 Main St",
      "city": "San Francisco",
      "state": "CA",
      "postal_code": "94101",
      "property_type": "apartment",
      "total_floors": 10,
      "total_units": 50,
      "year_built": 2015,
      "amenities": ["gym", "pool", "parking"],
      "created_at": "2025-01-01T00:00:00Z"
    }
  ]
}
```

---

### 37. Create Building
**Endpoint:** `POST /api/properties/buildings/`  
**Access:** Admin

**Request Body:**
```json
{
  "name": "Building C",
  "address": "789 Oak St",
  "city": "San Francisco",
  "state": "CA",
  "postal_code": "94103",
  "property_type": "apartment",
  "total_floors": 8,
  "total_units": 40,
  "year_built": 2020,
  "amenities": ["gym", "parking", "rooftop"],
  "description": "Modern luxury apartments"
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "name": "Building C",
  "message": "Building created successfully"
}
```

---

### 38. Get Building Details
**Endpoint:** `GET /api/properties/buildings/{building_id}/`  
**Access:** Admin/Staff

**Response (200):**
```json
{
  "id": "uuid",
  "name": "Building A",
  "address": "123 Main St",
  "total_units": 50,
  "occupied_units": 48,
  "available_units": 2,
  "occupancy_rate": 96.0,
  "units": [ /* list of units */ ]
}
```

---

### 39. List Units
**Endpoint:** `GET /api/properties/units/`  
**Access:** Admin/Staff  
**Query Parameters:**
- `building`: Filter by building ID
- `status`: Filter by status (available, occupied, maintenance)
- `unit_type`: Filter by type (studio, 1bhk, 2bhk)
- `min_rent`: Minimum rent
- `max_rent`: Maximum rent

**Response (200):**
```json
{
  "count": 50,
  "results": [
    {
      "id": "uuid",
      "building": {
        "id": "uuid",
        "name": "Building A"
      },
      "unit_number": "101",
      "floor": 1,
      "unit_type": "2bhk",
      "area_sqft": 1200.00,
      "bedrooms": 2,
      "bathrooms": 2,
      "monthly_rent": 2500.00,
      "security_deposit": 5000.00,
      "status": "occupied",
      "current_tenant": {
        "id": "uuid",
        "full_name": "John Doe"
      }
    }
  ]
}
```

---

### 40. Create Unit
**Endpoint:** `POST /api/properties/units/`  
**Access:** Admin

**Request Body:**
```json
{
  "building": "building-uuid",
  "unit_number": "205",
  "floor": 2,
  "unit_type": "2bhk",
  "area_sqft": 1200.00,
  "bedrooms": 2,
  "bathrooms": 2,
  "monthly_rent": 2500.00,
  "security_deposit": 5000.00,
  "status": "available",
  "features": ["balcony", "parking", "pet-friendly"]
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "unit_number": "205",
  "message": "Unit created successfully"
}
```

---

### 41. Update Unit
**Endpoint:** `PATCH /api/properties/units/{unit_id}/`  
**Access:** Admin

**Request Body:**
```json
{
  "status": "occupied",
  "current_tenant": "tenant-uuid",
  "monthly_rent": 2600.00
}
```

**Response (200):**
```json
{
  "message": "Unit updated successfully",
  "unit": { /* updated unit */ }
}
```

---

### 42. Assign Tenant to Unit
**Endpoint:** `POST /api/properties/units/{unit_id}/assign-tenant/`  
**Access:** Admin

**Request Body:**
```json
{
  "tenant_id": "uuid",
  "lease_start_date": "2025-11-01",
  "lease_end_date": "2026-10-31",
  "monthly_rent": 2500.00,
  "security_deposit": 5000.00
}
```

**Response (200):**
```json
{
  "message": "Tenant assigned successfully",
  "lease": {
    "id": "uuid",
    "tenant": "John Doe",
    "unit": "101",
    "start_date": "2025-11-01",
    "end_date": "2026-10-31"
  }
}
```

---

### 43. List Leases
**Endpoint:** `GET /api/properties/leases/`  
**Access:** Admin/Staff  
**Query Parameters:**
- `tenant`: Filter by tenant ID
- `unit`: Filter by unit ID
- `status`: Filter by status (active, expired, terminated)
- `expiring_soon`: Show leases expiring in next N days

**Response (200):**
```json
{
  "count": 100,
  "results": [
    {
      "id": "uuid",
      "unit": {
        "unit_number": "101",
        "building_name": "Building A"
      },
      "tenant": {
        "id": "uuid",
        "full_name": "John Doe",
        "email": "john@example.com"
      },
      "start_date": "2024-01-01",
      "end_date": "2025-12-31",
      "monthly_rent": 2500.00,
      "security_deposit": 5000.00,
      "status": "active",
      "is_active": true,
      "days_until_expiry": 71
    }
  ]
}
```

---

### 44. Property Dashboard Statistics
**Endpoint:** `GET /api/properties/dashboard/stats/`  
**Access:** Admin/Staff

**Response (200):**
```json
{
  "total_buildings": 5,
  "total_units": 250,
  "occupied_units": 235,
  "available_units": 10,
  "maintenance_units": 5,
  "occupancy_rate": 94.0,
  "total_monthly_revenue": 587500.00,
  "active_leases": 235,
  "expiring_leases_30_days": 12,
  "expiring_leases_60_days": 28,
  "average_rent": 2500.00,
  "by_building": [
    {
      "building_name": "Building A",
      "total_units": 50,
      "occupied": 48,
      "occupancy_rate": 96.0
    }
  ]
}
```

---

### 45. Occupancy Report
**Endpoint:** `GET /api/properties/reports/occupancy/`  
**Access:** Admin/Staff  
**Query Parameters:**
- `building`: Filter by building
- `date_from`: Start date
- `date_to`: End date

**Response (200):**
```json
{
  "report_date": "2025-10-21",
  "overall_occupancy": 94.0,
  "total_units": 250,
  "occupied_units": 235,
  "buildings": [
    {
      "building_name": "Building A",
      "total_units": 50,
      "occupied_units": 48,
      "available_units": 2,
      "occupancy_rate": 96.0
    }
  ]
}
```

---

### 46. Lease Expiry Report
**Endpoint:** `GET /api/properties/reports/lease-expiry/`  
**Access:** Admin/Staff  
**Query Parameters:**
- `days`: Leases expiring within N days (default: 30)

**Response (200):**
```json
{
  "expiring_within_days": 30,
  "total_expiring": 12,
  "leases": [
    {
      "tenant": "John Doe",
      "unit": "101",
      "building": "Building A",
      "end_date": "2025-11-15",
      "days_until_expiry": 25,
      "monthly_rent": 2500.00,
      "contact": "john@example.com"
    }
  ]
}
```

---

## 🔑 Roles & Permissions

### 47. List Roles
**Endpoint:** `GET /api/accounts/roles/`  
**Access:** Admin

**Response (200):**
```json
{
  "count": 7,
  "results": [
    {
      "id": "uuid",
      "name": "master_admin",
      "display_name": "Master Admin",
      "description": "Product owners with full system access",
      "level": 10,
      "permissions": [
        "manage_all_tenants",
        "manage_system_settings",
        "manage_all_users"
      ],
      "is_system_role": true,
      "is_active": true
    },
    {
      "id": "uuid",
      "name": "facility_manager",
      "display_name": "Facility Manager",
      "description": "Community property managers",
      "level": 6,
      "permissions": [
        "manage_residents",
        "manage_properties",
        "manage_maintenance"
      ],
      "is_system_role": false,
      "is_active": true
    }
  ]
}
```

---

### 48. Get Role Details
**Endpoint:** `GET /api/accounts/roles/{role_id}/`  
**Access:** Admin

**Response (200):**
```json
{
  "id": "uuid",
  "name": "facility_manager",
  "display_name": "Facility Manager",
  "description": "Manages daily property operations",
  "level": 6,
  "permissions": [
    "manage_residents",
    "approve_residents",
    "manage_properties",
    "manage_units",
    "view_reports"
  ],
  "is_system_role": false,
  "is_active": true,
  "user_count": 15
}
```

---

### 49. List Permissions
**Endpoint:** `GET /api/accounts/permissions/`  
**Access:** Admin  
**Query Parameters:**
- `category`: Filter by category

**Response (200):**
```json
{
  "count": 50,
  "results": [
    {
      "id": "uuid",
      "code": "manage_residents",
      "name": "Manage Residents",
      "description": "Can add, edit, delete residents",
      "category": "user",
      "is_active": true
    },
    {
      "id": "uuid",
      "code": "approve_residents",
      "name": "Approve Residents",
      "description": "Can approve or reject resident registrations",
      "category": "user",
      "is_active": true
    }
  ]
}
```

---

### 50. Assign Role to User
**Endpoint:** `POST /api/accounts/users/{user_id}/assign-role/`  
**Access:** Admin

**Request Body:**
```json
{
  "role": "role-uuid",
  "valid_from": "2025-10-21",
  "valid_until": "2026-10-21",
  "notes": "Temporary facility manager assignment"
}
```

**Response (200):**
```json
{
  "message": "Role assigned successfully",
  "user_role": {
    "role": "Facility Manager",
    "assigned_at": "2025-10-21T10:00:00Z",
    "valid_from": "2025-10-21",
    "valid_until": "2026-10-21"
  }
}
```

---

## 📊 Dashboard & Analytics

### 51. Dashboard Statistics (Admin)
**Endpoint:** `GET /api/accounts/dashboard/stats/`  
**Access:** Admin/Staff

**Response (200):**
```json
{
  "users": {
    "total": 150,
    "active": 145,
    "pending_approval": 5,
    "new_this_month": 12
  },
  "properties": {
    "total_buildings": 5,
    "total_units": 250,
    "occupied_units": 235,
    "occupancy_rate": 94.0
  },
  "revenue": {
    "monthly_total": 587500.00,
    "collected": 550000.00,
    "pending": 37500.00
  },
  "maintenance": {
    "open_requests": 15,
    "in_progress": 8,
    "completed_this_month": 45
  },
  "recent_activities": [
    {
      "user": "John Doe",
      "action": "registered",
      "timestamp": "2025-10-21T09:30:00Z"
    }
  ]
}
```

---

### 52. Activity Logs
**Endpoint:** `GET /api/accounts/activity/`  
**Access:** Admin/Staff  
**Query Parameters:**
- `user`: Filter by user ID
- `action`: Filter by action type
- `date_from`: Start date
- `date_to`: End date
- `page`: Page number

**Response (200):**
```json
{
  "count": 500,
  "results": [
    {
      "id": "uuid",
      "user": {
        "id": "uuid",
        "username": "john_doe",
        "full_name": "John Doe"
      },
      "action": "user_login",
      "description": "User john_doe logged in",
      "ip_address": "192.168.1.100",
      "tenant_schema": "skyline",
      "created_at": "2025-10-21T09:30:00Z",
      "metadata": {
        "browser": "Chrome",
        "device": "Desktop"
      }
    }
  ]
}
```

---

### 53. Notification Preferences
**Endpoint:** `GET /api/accounts/notification-preferences/`  
**Access:** Authenticated

**Response (200):**
```json
{
  "email_notifications": true,
  "sms_notifications": false,
  "push_notifications": true,
  "notification_types": {
    "maintenance_updates": true,
    "payment_reminders": true,
    "community_announcements": true,
    "emergency_alerts": true
  }
}
```

---

### 54. Update Notification Preferences
**Endpoint:** `PUT /api/accounts/notification-preferences/`  
**Access:** Authenticated

**Request Body:**
```json
{
  "email_notifications": true,
  "sms_notifications": true,
  "notification_types": {
    "maintenance_updates": true,
    "payment_reminders": false,
    "community_announcements": true
  }
}
```

**Response (200):**
```json
{
  "message": "Preferences updated successfully",
  "preferences": { /* updated preferences */ }
}
```

---

## 🔍 Search & Filtering

### General Query Parameters (Most List Endpoints)

**Pagination:**
- `page`: Page number (default: 1)
- `page_size`: Results per page (default: 20, max: 100)

**Search:**
- `search`: Search across multiple fields

**Sorting:**
- `ordering`: Sort field (prefix with `-` for descending)
  - Example: `ordering=-created_at` (newest first)
  - Example: `ordering=name` (alphabetical)

**Date Filters:**
- `date_from`: Start date (YYYY-MM-DD)
- `date_to`: End date (YYYY-MM-DD)
- `created_after`: Created after date
- `created_before`: Created before date

---

## ⚠️ Error Responses

### 400 Bad Request
```json
{
  "error": "Validation error",
  "details": {
    "email": ["This field is required."],
    "phone": ["Enter a valid phone number."]
  }
}
```

---

### 401 Unauthorized
```json
{
  "detail": "Authentication credentials were not provided."
}
```

---

### 403 Forbidden
```json
{
  "detail": "You do not have permission to perform this action."
}
```

---

### 404 Not Found
```json
{
  "detail": "Not found."
}
```

---

### 500 Internal Server Error
```json
{
  "error": "Internal server error",
  "message": "An unexpected error occurred. Please try again later."
}
```

---

## 🔐 Authentication Flow

### For Frontend Implementation

**1. Login Flow:**
```javascript
// POST /api/accounts/login/
const response = await fetch('http://localhost:8000/api/accounts/login/', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    username: 'john_doe',
    password: 'SecurePass123!'
  })
});

const data = await response.json();
// Store tokens
localStorage.setItem('access_token', data.access);
localStorage.setItem('refresh_token', data.refresh);
localStorage.setItem('user', JSON.stringify(data.user));
```

---

**2. Authenticated Requests:**
```javascript
const token = localStorage.getItem('access_token');

const response = await fetch('http://localhost:8000/api/accounts/me/', {
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  }
});
```

---

**3. Token Refresh:**
```javascript
const refreshToken = localStorage.getItem('refresh_token');

const response = await fetch('http://localhost:8000/api/accounts/token/refresh/', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ refresh: refreshToken })
});

const data = await response.json();
localStorage.setItem('access_token', data.access);
```

---

**4. Logout:**
```javascript
localStorage.removeItem('access_token');
localStorage.removeItem('refresh_token');
localStorage.removeItem('user');
// Redirect to login
```

---

## 📤 File Upload Examples

### Avatar Upload
```javascript
const formData = new FormData();
formData.append('avatar', fileInput.files[0]);
formData.append('first_name', 'John');
formData.append('last_name', 'Doe');

const response = await fetch('http://localhost:8000/api/accounts/profile/', {
  method: 'PUT',
  headers: {
    'Authorization': `Bearer ${token}`
    // Don't set Content-Type for FormData
  },
  body: formData
});
```

---

### CSV Upload
```javascript
const formData = new FormData();
formData.append('file', csvFile);
formData.append('upload_type', 'residents');
formData.append('auto_approve', false);

const response = await fetch('http://localhost:8000/api/accounts/csv/upload/', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`
  },
  body: formData
});

const data = await response.json();
// Poll for status
const statusResponse = await fetch(
  `http://localhost:8000/api/accounts/csv/uploads/${data.upload_id}/`,
  {
    headers: { 'Authorization': `Bearer ${token}` }
  }
);
```

---

## 🎫 Visitors Management

### 55. List Visitors
**Endpoint:** `GET /api/visitors/visitors/`  
**Access:** Authenticated  
**Description:** Get list of all visitors or search by phone/name.

### 56. Register Visitor (Pass)
**Endpoint:** `POST /api/visitors/passes/`  
**Access:** Authenticated  
**Description:** Create a new visitor pass.

### 57. Check In/Out Visitor
**Endpoint:** `POST /api/visitors/passes/{id}/check_in/` & `check_out/`  
**Access:** Authenticated (Security/Admin)

---

## 🛠️ Maintenance System

### 58. Create Maintenance Request
**Endpoint:** `POST /api/maintenance/requests/`  
**Access:** Authenticated  
**Description:** Submit a new maintenance ticket.

### 59. Update Maintenance Status
**Endpoint:** `PATCH /api/maintenance/requests/{id}/update-status/`  
**Access:** Admin/Staff  

---

## 🎾 Amenities & Bookings

### 60. List Available Amenities
**Endpoint:** `GET /api/amenities/amenities/available/`  
**Access:** Authenticated

### 61. Book Amenity
**Endpoint:** `POST /api/amenities/bookings/`  
**Access:** Authenticated  
**Description:** Request to book an amenity.

---

## ⚡ Utilities Management

### 62. My Utility Bills
**Endpoint:** `GET /api/utilities/bills/my/`  
**Access:** Authenticated (Tenant)

### 63. Generate Utility Bills
**Endpoint:** `POST /api/utilities/bills/generate_bills/`  
**Access:** Admin/Staff

---

## 📅 Calendar & Alerts

### 64. My Calendar Alerts
**Endpoint:** `GET /api/calendar-alerts/alerts/my_alerts/`  
**Access:** Authenticated  
**Description:** Get alerts relevant to the current user.

### 65. Today's Alerts
**Endpoint:** `GET /api/calendar-alerts/alerts/today/`  
**Access:** Authenticated

---

## 🚀 Rate Limits

**Current Limits:**
- Authentication endpoints: 5 requests per minute
- General API: 100 requests per minute
- CSV uploads: 10 per hour
- File uploads: 50 MB max file size

---

## 📝 CSV File Format

### Residents CSV Template

**Required Columns:**
- username
- email
- first_name
- last_name
- phone

**Optional Columns:**
- unit_number
- building_name
- emergency_contact_name
- emergency_contact_phone
- date_of_birth (YYYY-MM-DD)
- gender (male/female/other)
- occupation

**Example CSV:**
```csv
username,email,first_name,last_name,phone,unit_number,building_name,emergency_contact_name,emergency_contact_phone
john_doe,john@example.com,John,Doe,+1234567890,101,Building A,Jane Doe,+0987654321
jane_smith,jane@example.com,Jane,Smith,+1234567891,102,Building A,John Smith,+0987654322
```

**Notes:**
- Maximum 1000 rows per CSV
- Duplicate emails/usernames will be skipped
- Invalid phone numbers will be rejected
- Empty required fields will cause row to fail

---

## 🎯 Common Use Cases

### 1. Admin Creates New Resident
```
1. POST /api/accounts/people-hub/residents/
2. Resident receives temporary password via email
3. Resident logs in and updates profile
4. Admin approves: PATCH /api/accounts/people-hub/residents/{id}/ 
   with {is_approved: true}
```

---

### 2. Bulk Import Residents
```
1. GET /api/accounts/csv/template/?upload_type=residents
2. Fill CSV with resident data
3. POST /api/accounts/csv/upload/ (file upload)
4. GET /api/accounts/csv/uploads/{id}/ (check status)
5. GET /api/accounts/csv/uploads/{id}/results/ (view results)
6. Bulk approve: POST /api/accounts/people-hub/residents/bulk_action/
```

---

### 3. Assign Tenant to Unit
```
1. GET /api/properties/units/?status=available
2. POST /api/properties/units/{unit_id}/assign-tenant/
3. System creates lease automatically
4. Unit status changes to "occupied"
```

---

### 4. Super Admin Creates New Client
```
1. POST /api/tenants/clients/
2. System creates database schema
3. POST /api/tenants/domains/ (add domain)
4. PUT /api/tenants/clients/{id}/features/ (enable features)
5. Client can access via custom domain
```

---

## 🛠️ Testing with cURL

### Login
```bash
curl -X POST http://localhost:8000/api/accounts/login/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "admin123"
  }'
```

---

### Get Current User
```bash
curl -X GET http://localhost:8000/api/accounts/me/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

### List Residents
```bash
curl -X GET "http://localhost:8000/api/accounts/people-hub/residents/?page=1&page_size=10" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

### Upload CSV
```bash
curl -X POST http://localhost:8000/api/accounts/csv/upload/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -F "file=@residents.csv" \
  -F "upload_type=residents" \
  -F "auto_approve=false"
```

---

## 📞 Support

**Backend Documentation:** Auto-generated with drf-spectacular  
**Swagger UI:** `http://localhost:8000/api/schema/swagger-ui/`  
**ReDoc:** `http://localhost:8000/api/schema/redoc/`  
**OpenAPI Schema:** `http://localhost:8000/api/schema/`

---

## ✅ Checklist for Frontend Developers

- [ ] Implement JWT token storage and refresh
- [ ] Handle 401 errors and redirect to login
- [ ] Implement file upload with progress tracking
- [ ] Add CSV validation before upload
- [ ] Implement pagination for list views
- [ ] Add search/filter functionality
- [ ] Handle loading states
- [ ] Display error messages from API
- [ ] Implement role-based UI rendering
- [ ] Add tenant context detection
- [ ] Test all CRUD operations
- [ ] Implement bulk actions
- [ ] Add export functionality

---

**Last Updated:** October 21, 2025  
**Status:** MVP Ready ✅